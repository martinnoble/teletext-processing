#!/usr/bin/env python3
"""Unit tests for [`t42restream.py`](t42restream.py)."""

import os
import tempfile
import unittest
from io import BytesIO

import t42restream
from teletext_helpers import hamming_8_4_encode


class TestRestreamMagazineParallel(unittest.TestCase):
    def _make_packet(self, magazine, packet_number, fill_byte):
        combined = (packet_number << 3) | (magazine & 0x07)
        packet = bytearray([fill_byte] * t42restream.PACKET_SIZE)
        packet[0] = hamming_8_4_encode(combined & 0x0F)
        packet[1] = hamming_8_4_encode((combined >> 4) & 0x0F)
        return bytes(packet)

    def _make_header_packet(self, magazine, page_hex, fill_byte, subcode=0):
        packet = bytearray(self._make_packet(magazine, 0, fill_byte))
        packet[2] = hamming_8_4_encode(int(page_hex[2], 16))
        packet[3] = hamming_8_4_encode(int(page_hex[1], 16))
        packet[4] = hamming_8_4_encode(subcode & 0x0F)
        packet[5] = hamming_8_4_encode((subcode >> 4) & 0x07)
        packet[6] = hamming_8_4_encode((subcode >> 7) & 0x0F)
        packet[7] = hamming_8_4_encode((subcode >> 11) & 0x03)
        return bytes(packet)

    def test_magazine_parallel_orders_each_magazine_line_by_page_then_subpage(self):
        packets = [
            self._make_header_packet(2, "220", 0x20),
            self._make_packet(2, 1, 0x21),
            self._make_header_packet(1, "120", 0x22),
            self._make_packet(1, 1, 0x23),
            self._make_header_packet(1, "110", 0x24),
            self._make_packet(1, 1, 0x25),
            self._make_header_packet(1, "110", 0x26, subcode=1),
            self._make_packet(1, 1, 0x27),
            self._make_header_packet(2, "210", 0x28),
            self._make_packet(2, 1, 0x29),
            self._make_header_packet(2, "210", 0x2A, subcode=1),
            self._make_packet(2, 1, 0x2B),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                magazine_parallel=True,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        packet_size = t42restream.PACKET_SIZE
        emitted_packets = [
            emitted[i:i + packet_size]
            for i in range(0, len(emitted), packet_size)
        ]
        emitted_page_ids = [
            (
                "%X%X%X" % (
                    t42restream._parse_packet_address(packet)[0],
                    *t42restream._parse_page_sort_key(packet)[:2],
                ),
                t42restream._parse_page_sort_key(packet)[2],
            )
            for packet in emitted_packets
            if t42restream._parse_packet_address(packet)[1] == 0
        ]

        # The schedule gives mags 1 and 2 proportional bandwidth (equal pages
        # each), so each occupies multiple VBI lines per field.  Headers are
        # deferred to the primary line; content is held until the next field.
        # max_cycles=2 (max subpage count per slot), so two full rotations
        # are emitted — the ordering pattern repeats twice.
        one_cycle = [
            ("110", 0),
            ("210", 0),
            ("120", 0),
            ("220", 0),
            ("110", 1),
            ("210", 1),
            ("120", 0),
            ("220", 0),
        ]
        self.assertEqual(emitted_page_ids, one_cycle * 2)

    def test_magazine_parallel_interleaves_content_across_magazines(self):
        """
        With two magazines of equal page count the DRR scheduler awards credits
        of 0.5 per slot to each.  They alternate strictly: slot 0 → mag 1,
        slot 1 → mag 2, then both are locked (headers emitted), slots 2-7
        → fillers.

        Mag 1 pages: 110/sub0, 110/sub1 (1 slot, 2 subpages, max_cycles=2).
        Mag 2 pages: 210/sub0, 220/sub0 (2 slots, 1 subpage each, max_cycles=2).

        The 40-packet trace below is the exact output produced by the scheduler.
        """
        packets = [
            self._make_header_packet(2, "220", 0x20),
            self._make_packet(2, 1, 0x21),
            self._make_header_packet(1, "110", 0x22),
            self._make_packet(1, 1, 0x23),
            self._make_header_packet(1, "110", 0x24, subcode=1),
            self._make_packet(1, 1, 0x25),
            self._make_header_packet(2, "210", 0x26),
            self._make_packet(2, 1, 0x27),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                magazine_parallel=True,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        packet_size = t42restream.PACKET_SIZE
        emitted_packets = [
            emitted[i:i + packet_size]
            for i in range(0, len(emitted), packet_size)
        ]
        filler_packets = {
            magazine: bytes([
                hamming_8_4_encode(((25 << 3) | (magazine & 0x07)) & 0x0F),
                hamming_8_4_encode((((25 << 3) | (magazine & 0x07)) >> 4) & 0x0F),
                *([t42restream.encode_text_byte(' ')] * (packet_size - 2)),
            ])
            for magazine in range(1, 9)
        }
        filler_by_packet = {v: k for k, v in filler_packets.items()}
        emitted_summary = [
            ("FILLER", filler_by_packet[packet]) if packet in filler_by_packet
            else t42restream._parse_packet_address(packet)
            for packet in emitted_packets
        ]

        # DRR with equal weights: mags alternate strictly each slot.
        # Field 1: H1, H2, then 6 fillers (both locked after headers).
        # Fields 2-4: C1, C2, H1, H2, then 4 fillers each.
        # Field 5 (final): C1, C2, then 6 fillers (both exhausted).
        F1 = ("FILLER", 1)
        self.assertEqual(
            emitted_summary,
            [
                (1, 0), (2, 0), F1, F1, F1, F1, F1, F1,
                (1, 1), (2, 1), (1, 0), (2, 0), F1, F1, F1, F1,
                (1, 1), (2, 1), (1, 0), (2, 0), F1, F1, F1, F1,
                (1, 1), (2, 1), (1, 0), (2, 0), F1, F1, F1, F1,
                (1, 1), (2, 1), F1, F1, F1, F1, F1, F1,
            ],
        )

    def test_magazine_parallel_two_sparse_magazines_interleave(self):
        """
        Mags 1 and 8 each have 1 page (header + 1 content row).
        field_schedule = [1,1,1,1,8,8,8,8] (proportional, sorted).

        Field 1: slot 0→H1 (locked); slots 1-3 fall through to mag 8→H8 at
        slot 1, then fillers×2; slots 4-7 both locked→fillers×4.
        Field 2: slot 0→C1 (exhausted); slot 1 falls through to mag 8→C8
        (exhausted); slots 2-7 both inactive→fillers×6.
        """
        packets = [
            self._make_header_packet(1, "110", 0x22),
            self._make_packet(1, 1, 0x23),
            self._make_header_packet(8, "810", 0x24),
            self._make_packet(8, 1, 0x25),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                magazine_parallel=True,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        packet_size = t42restream.PACKET_SIZE
        emitted_packets = [
            emitted[i:i + packet_size]
            for i in range(0, len(emitted), packet_size)
        ]
        filler_packets = {
            magazine: bytes([
                hamming_8_4_encode(((25 << 3) | (magazine & 0x07)) & 0x0F),
                hamming_8_4_encode((((25 << 3) | (magazine & 0x07)) >> 4) & 0x0F),
                *([t42restream.encode_text_byte(' ')] * (packet_size - 2)),
            ])
            for magazine in range(1, 9)
        }
        filler_by_packet = {v: k for k, v in filler_packets.items()}
        emitted_summary = [
            ("FILLER", filler_by_packet[packet]) if packet in filler_by_packet
            else t42restream._parse_packet_address(packet)
            for packet in emitted_packets
        ]

        # field_schedule = [1,1,1,1,8,8,8,8].
        # Field 1: H1, H8 (at slot 1 via fallback), then 6 fillers.
        # Field 2: C1, C8 (at slot 1 via fallback), then 6 fillers.
        F1 = ("FILLER", 1)
        self.assertEqual(
            emitted_summary,
            [
                (1, 0), (8, 0), F1, F1, F1, F1, F1, F1,
                (1, 1), (8, 1), F1, F1, F1, F1, F1, F1,
            ],
        )

    def test_magazine_parallel_stops_after_longest_real_magazine_without_loop(self):
        """
        Mag 1: 2 subpages (110/sub0, 110/sub1); mag 2: 1 page (210/sub0).
        Page counts 2 vs 1 → field_schedule = [1,1,1,1,1,2,2,2] (largest-
        remainder: mag1=5, mag2=3 of 8 slots).  max_cycles=2.
        The run produces exactly 40 packets.
        """
        packets = [
            self._make_header_packet(1, "110", 0x22),
            self._make_packet(1, 1, 0x23),
            self._make_header_packet(1, "110", 0x24, subcode=1),
            self._make_packet(1, 1, 0x25),
            self._make_header_packet(2, "210", 0x26),
            self._make_packet(2, 1, 0x27),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                magazine_parallel=True,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        packet_size = t42restream.PACKET_SIZE
        emitted_packets = [
            emitted[i:i + packet_size]
            for i in range(0, len(emitted), packet_size)
        ]

        # Verified by inspection: 40 packets total.
        self.assertEqual(len(emitted_packets), 40)

    def test_magazine_parallel_cannot_be_combined_with_interleave(self):
        with self.assertRaisesRegex(ValueError, "cannot be used together"):
            t42restream.restream(
                "unused.t42",
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=BytesIO(),
                interleave=True,
                magazine_parallel=True,
            )


    def test_magazine_parallel_no_content_in_same_field_as_header(self):
        """
        One page: header + one content row.  vbi_lines=2, only mag 1 active.
        field_schedule = [1, 1].

        Field 1:
          slot 0 (pref=1): emit header → mag 1 locked.
          slot 1 (pref=1): locked → no other mag → filler.

        Field 2:
          slot 0 (pref=1): emit content (pn=1) → mag 1 exhausted, removed.
          slot 1 (pref=1): mag 1 inactive → filler.

        Output: [header, FILLER, content, FILLER] — 4 packets.
        The field width is always maintained exactly.
        """
        packets = [
            self._make_header_packet(1, "110", 0x22),
            self._make_packet(1, 1, 0x23),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                magazine_parallel=True,
                vbi_lines=2,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        packet_size = t42restream.PACKET_SIZE
        emitted_packets = [
            emitted[i:i + packet_size]
            for i in range(0, len(emitted), packet_size)
        ]

        filler_mag1 = bytes([
            hamming_8_4_encode(((25 << 3) | 1) & 0x0F),
            hamming_8_4_encode((((25 << 3) | 1) >> 4) & 0x0F),
            *([t42restream.encode_text_byte(' ')] * (packet_size - 2)),
        ])

        packet_numbers = []
        for pkt in emitted_packets:
            if pkt == filler_mag1:
                packet_numbers.append("FILLER")
            else:
                _, pn = t42restream._parse_packet_address(pkt)
                packet_numbers.append(pn)

        # Field 1: header, filler.  Field 2: content, filler.
        self.assertEqual(packet_numbers, [0, "FILLER", 1, "FILLER"])


class TestRestreamInterleaved(unittest.TestCase):
    def _make_packet(self, magazine, packet_number, fill_byte):
        combined = (packet_number << 3) | (magazine & 0x07)
        packet = bytearray([fill_byte] * t42restream.PACKET_SIZE)
        packet[0] = hamming_8_4_encode(combined & 0x0F)
        packet[1] = hamming_8_4_encode((combined >> 4) & 0x0F)
        return bytes(packet)

    def _make_header_packet(self, magazine, page_hex, fill_byte, subcode=0):
        packet = bytearray(self._make_packet(magazine, 0, fill_byte))
        packet[2] = hamming_8_4_encode(int(page_hex[2], 16))
        packet[3] = hamming_8_4_encode(int(page_hex[1], 16))
        packet[4] = hamming_8_4_encode(subcode & 0x0F)
        packet[5] = hamming_8_4_encode((subcode >> 4) & 0x07)
        packet[6] = hamming_8_4_encode((subcode >> 7) & 0x0F)
        packet[7] = hamming_8_4_encode((subcode >> 11) & 0x03)
        return bytes(packet)

    def test_interleave_no_content_in_same_field_as_header(self):
        """
        In interleave mode, content packets of a page must not appear in the
        same VBI field as the page's own header packet.

        With vbi_lines=4, a page that has header + 1 content row should produce:
          Field 1: header, filler, filler, filler   (3 fillers pad to field boundary)
          Field 2: content-row, ...                 (content starts in next field)
        """
        packets = [
            self._make_header_packet(1, "110", 0x22),
            self._make_packet(1, 1, 0x23),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                interleave=True,
                vbi_lines=4,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        pkt_size = t42restream.PACKET_SIZE
        emitted_packets = [
            emitted[i:i + pkt_size]
            for i in range(0, len(emitted), pkt_size)
        ]

        filler_mag1 = bytes([
            hamming_8_4_encode(((25 << 3) | 1) & 0x0F),
            hamming_8_4_encode((((25 << 3) | 1) >> 4) & 0x0F),
            *([t42restream.encode_text_byte(' ')] * (pkt_size - 2)),
        ])

        labels = []
        for pkt in emitted_packets:
            if pkt == filler_mag1:
                labels.append("FILLER")
            else:
                _, pn = t42restream._parse_packet_address(pkt)
                labels.append(pn)

        # Field 1: header at slot 0, then 3 fillers to complete the 4-line field.
        # Field 2: content row (pn=1) at slot 0.
        self.assertEqual(labels, [0, "FILLER", "FILLER", "FILLER", 1])

    def test_interleave_header_only_page_no_padding(self):
        """
        A header-only page (no content rows) should not produce any filler
        padding after the header within the same field.  The next page's header
        will still be aligned to the start of the next field, but no padding is
        inserted when there are no content packets to separate.
        """
        packets = [
            self._make_header_packet(1, "110", 0x22),
        ]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"".join(packets))
            temp_path = temp_file.name

        try:
            output = BytesIO()
            t42restream.restream(
                temp_path,
                mask="?" * t42restream.HEADER_TEXT_LEN,
                time_format="",
                loop=False,
                output=output,
                interleave=True,
                vbi_lines=4,
            )
        finally:
            os.unlink(temp_path)

        emitted = output.getvalue()
        pkt_size = t42restream.PACKET_SIZE
        # Single header-only page: just the one header, no filler appended.
        self.assertEqual(len(emitted), pkt_size)
        _, pn = t42restream._parse_packet_address(emitted[:pkt_size])
        self.assertEqual(pn, 0)


if __name__ == "__main__":
    unittest.main()

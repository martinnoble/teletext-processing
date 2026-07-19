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
                t42restream._parse_page_hex(packet, t42restream._parse_packet_address(packet)[0]),
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

    def test_magazine_parallel_keeps_magazines_on_stable_packet_positions(self):
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

        # Mags 1 and 2 each have 2 pages so the schedule allocates 4 VBI lines
        # to each (proportional, 8 total).  With header-isolation, the 3 lines
        # that follow the header line in the same field emit fillers for that
        # magazine; content resumes from the next field onwards.
        # max_cycles=2 (longest slot has 2 subpages), so two full rotations run.
        # Both magazines exhaust on the same final field, so no trailing fillers.
        F1 = ("FILLER", 1)
        F2 = ("FILLER", 2)
        self.assertEqual(
            emitted_summary,
            [
                (1, 0), F1, F1, F1, (2, 0), F2, F2, F2,
                (1, 1), F1, F1, F1, (2, 1), F2, F2, F2,
                (1, 0), F1, F1, F1, (2, 0), F2, F2, F2,
                (1, 1), F1, F1, F1, (2, 1), F2, F2, F2,
                (1, 0), F1, F1, F1, (2, 0), F2, F2, F2,
                (1, 1), F1, F1, F1, (2, 1), F2, F2, F2,
                (1, 0), F1, F1, F1, (2, 0), F2, F2, F2,
                (1, 1), (2, 1),
            ],
        )

    def test_magazine_parallel_outputs_filler_for_missing_magazines(self):
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

        # Only mags 1 and 8 are active, so the proportional schedule divides
        # all 8 VBI lines between them (4 each).  Mags 2–7 receive no lines and
        # therefore produce no output.  With header-isolation the 3 lines that
        # follow the header line for each magazine in the same field emit fillers
        # for that magazine; content arrives in the next field.
        F1 = ("FILLER", 1)
        F8 = ("FILLER", 8)
        self.assertEqual(
            emitted_summary,
            [
                (1, 0), F1, F1, F1, (8, 0), F8, F8, F8,
                (1, 1), (8, 1),
            ],
        )

    def test_magazine_parallel_stops_after_longest_real_magazine_without_loop(self):
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

        # Mag 1 has 2 subpages (110/sub0, 110/sub1) → 1 slot, 2 subpages,
        # max_cycles=2.  Mag 2 has 1 page → 1 slot, 1 subpage.  With
        # proportional scheduling mag 1 gets more VBI lines than mag 2, and
        # header-isolation inserts fillers after each header in the same field.
        # The run terminates once the longest magazine (mag 1) completes 2 full
        # subpage cycles; mag 2 runs until it is displaced by mag 1 exhausting.
        self.assertEqual(len(emitted_packets), 46)

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
        When a magazine occupies multiple VBI lines in a field, content packets
        must not appear on any of those lines in the same field as the header.
        Filler should be substituted until the next field.
        """
        # One page: header + one content row.  With vbi_lines=2 the single
        # magazine gets both slots, so in the first field:
        #   slot 0 (primary) → header
        #   slot 1           → filler  (header was already emitted this field)
        # In the second field:
        #   slot 0           → content packet (packet_number=1)
        #   slot 1           → filler (magazine has no more packets for this page)
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

        # Field 1: header on slot 0, filler on slot 1 (no content same field as header)
        # Field 2: content (pn=1) on slot 0; magazine exhausted so slot 1 is silent
        self.assertEqual(packet_numbers, [0, "FILLER", 1])


if __name__ == "__main__":
    unittest.main()

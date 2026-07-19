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

        self.assertEqual(
            emitted_page_ids,
            [
                ("110", 0),
                ("210", 0),
                ("120", 0),
                ("220", 0),
                ("110", 1),
                ("210", 1),
                ("120", 0),
                ("220", 0),
            ],
        )

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
        emitted_summary = [
            ("FILLER", magazine) if packet == filler_packets[magazine] else t42restream._parse_packet_address(packet)
            for packet in emitted_packets
            for magazine in range(1, 9)
            if packet == filler_packets[magazine] or magazine == 8
        ]

        self.assertEqual(
            emitted_summary,
            [
                (1, 0), (2, 0), ("FILLER", 3), ("FILLER", 4), ("FILLER", 5), ("FILLER", 6), ("FILLER", 7), ("FILLER", 8),
                (1, 1), (2, 1), ("FILLER", 3), ("FILLER", 4), ("FILLER", 5), ("FILLER", 6), ("FILLER", 7), ("FILLER", 8),
                (1, 0), (2, 0), ("FILLER", 3), ("FILLER", 4), ("FILLER", 5), ("FILLER", 6), ("FILLER", 7), ("FILLER", 8),
                (1, 1), (2, 1), ("FILLER", 3), ("FILLER", 4), ("FILLER", 5), ("FILLER", 6), ("FILLER", 7), ("FILLER", 8),
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
        emitted_summary = [
            ("FILLER", magazine) if packet == filler_packets[magazine] else t42restream._parse_packet_address(packet)
            for packet in emitted_packets
            for magazine in range(1, 9)
            if packet == filler_packets[magazine] or magazine == 8
        ]

        self.assertEqual(
            emitted_summary,
            [
                (1, 0), ("FILLER", 2), ("FILLER", 3), ("FILLER", 4),
                ("FILLER", 5), ("FILLER", 6), ("FILLER", 7), (8, 0),
                (1, 1), ("FILLER", 2), ("FILLER", 3), ("FILLER", 4),
                ("FILLER", 5), ("FILLER", 6), ("FILLER", 7), (8, 1),
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

        self.assertEqual(len(emitted_packets), 16)

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


if __name__ == "__main__":
    unittest.main()

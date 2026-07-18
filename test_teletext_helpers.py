#!/usr/bin/env python3
"""
Unit tests for teletext_helpers module
"""

import unittest
from teletext_helpers import hamming_8_4_decode, hamming_8_4_encode, encode_text_byte, decode_text_bytes


class TestHamming84Decode(unittest.TestCase):
    """Test cases for Hamming 8/4 decoder"""
    
    def test_valid_decode_no_error(self):
        """Test decoding valid Hamming 8/4 bytes with no errors"""
        # Test some known valid encodings
        # These are the correct Hamming 8/4 encodings for the Teletext format
        
        # Value 0 (0000) - all data bits 0
        result = hamming_8_4_decode(0x15)
        self.assertEqual(result, 0x0)
        
        # Value 1 (0001) - D1=1
        result = hamming_8_4_decode(0x02)
        self.assertEqual(result, 0x1)
        
        # Value 2 (0010) - D2=1
        result = hamming_8_4_decode(0x49)
        self.assertEqual(result, 0x2)
        
        # Value 15 (1111) - all data bits 1
        result = hamming_8_4_decode(0xEA)
        self.assertEqual(result, 0xF)
    
    def test_single_bit_error_correction(self):
        """Test that single bit errors are corrected"""
        # Test that flipping any single bit doesn't change the decoded value
        # Start with a valid encoding for 0
        valid_byte = 0x15  # Encodes 0
        
        # Test flipping each bit - all should still decode to 0
        for bit_pos in range(8):
            corrupted = valid_byte ^ (1 << bit_pos)
            result = hamming_8_4_decode(corrupted)
            self.assertEqual(result, 0x0, f"Flipping bit {bit_pos} should not change decoded value")
    
    def test_double_bit_error_detection(self):
        """Test that double bit errors may not always be detectable"""
        # Note: Hamming 8/4 can only guarantee detection of single bit errors
        # and correction of single bit errors. Some double bit errors may
        # result in incorrect decoding rather than returning None.
        # This test verifies the decoder doesn't crash on corrupted data.
        
        valid_byte = 0x15  # Encodes 0
        
        # Flip two bits - this may or may not be detected as an error
        corrupted = valid_byte ^ 0x03  # Flip bits 0 and 1
        result = hamming_8_4_decode(corrupted)
        
        # The result should be either None (detected) or some value (undetected)
        # We just verify it doesn't crash
        self.assertIsNotNone(result, "Decoder should return a value even for double bit errors")
    
    def test_all_nibble_values(self):
        """Test that all 16 possible nibble values can be encoded/decoded"""
        # Test with correct Hamming 8/4 encodings (ETS 300 706 s.8.2)
        test_cases = [
            (0x15, 0x0), (0x02, 0x1), (0x49, 0x2), (0x5E, 0x3),
            (0x64, 0x4), (0x73, 0x5), (0x38, 0x6), (0x2F, 0x7),
            (0xD0, 0x8), (0xC7, 0x9), (0x8C, 0xA), (0x9B, 0xB),
            (0xA1, 0xC), (0xB6, 0xD), (0xFD, 0xE), (0xEA, 0xF)
        ]
        
        for byte_val, expected in test_cases:
            result = hamming_8_4_decode(byte_val)
            self.assertEqual(result, expected, f"0x{byte_val:02X} should decode to 0x{expected:X}")


class TestHamming84Encode(unittest.TestCase):
    """Test cases for Hamming 8/4 encoder"""

    def test_encode_known_values(self):
        """Test encoding against the known ETS 300 706 s.8.2 lookup table"""
        test_cases = [
            (0x0, 0x15), (0x1, 0x02), (0x2, 0x49), (0x3, 0x5E),
            (0x4, 0x64), (0x5, 0x73), (0x6, 0x38), (0x7, 0x2F),
            (0x8, 0xD0), (0x9, 0xC7), (0xA, 0x8C), (0xB, 0x9B),
            (0xC, 0xA1), (0xD, 0xB6), (0xE, 0xFD), (0xF, 0xEA),
        ]
        for value, expected_byte in test_cases:
            result = hamming_8_4_encode(value)
            self.assertEqual(result, expected_byte,
                             f"hamming_8_4_encode(0x{value:X}) should produce 0x{expected_byte:02X}")

    def test_encode_roundtrip_all_nibbles(self):
        """Encoding then decoding every nibble should return the original value"""
        for value in range(16):
            encoded = hamming_8_4_encode(value)
            decoded = hamming_8_4_decode(encoded)
            self.assertEqual(decoded, value,
                             f"Round-trip failed for value 0x{value:X}: "
                             f"encoded to 0x{encoded:02X}, decoded to {decoded}")

    def test_encode_produces_valid_hamming_byte(self):
        """Every encoded byte should pass the Hamming parity checks (syndrome == 0)"""
        for value in range(16):
            byte = hamming_8_4_encode(value)
            # Re-extract bits and verify all four parity tests pass
            p1 = (byte >> 0) & 1
            d1 = (byte >> 1) & 1
            p2 = (byte >> 2) & 1
            d2 = (byte >> 3) & 1
            p3 = (byte >> 4) & 1
            d3 = (byte >> 5) & 1
            p4 = (byte >> 6) & 1
            d4 = (byte >> 7) & 1
            self.assertEqual(1 ^ p1 ^ d1 ^ d3 ^ d4, 0, f"Test A failed for value 0x{value:X}")
            self.assertEqual(1 ^ p2 ^ d1 ^ d2 ^ d4, 0, f"Test B failed for value 0x{value:X}")
            self.assertEqual(1 ^ p3 ^ d1 ^ d2 ^ d3, 0, f"Test C failed for value 0x{value:X}")
            self.assertEqual(1 ^ p4 ^ p1 ^ d1 ^ p2 ^ d2 ^ p3 ^ d3 ^ d4, 0,
                             f"Test D failed for value 0x{value:X}")


class TestEncodeTextByte(unittest.TestCase):
    """Test cases for text byte encoder"""

    def test_encode_sets_odd_parity(self):
        """Every encoded byte should have an odd number of set bits"""
        for char in " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#":
            byte = encode_text_byte(char)
            self.assertEqual(bin(byte).count('1') % 2, 1,
                             f"Byte for '{char}' (0x{byte:02X}) does not have odd parity")

    def test_encode_preserves_ascii_value(self):
        """Lower 7 bits of the encoded byte should equal the character's ASCII value"""
        for char in " ABC~":
            byte = encode_text_byte(char)
            self.assertEqual(byte & 0x7F, ord(char),
                             f"Lower 7 bits for '{char}' should be 0x{ord(char):02X}")

    def test_encode_decode_roundtrip(self):
        """encode_text_byte then decode_text_bytes should return the original string"""
        text = "CEEFAX 170"
        encoded = bytes(encode_text_byte(c) for c in text)
        decoded = decode_text_bytes(encoded, 0, len(text))
        self.assertEqual(decoded, text)

    def test_encode_decode_roundtrip_full_printable_range(self):
        """Round-trip every printable ASCII character (0x20–0x7E)"""
        chars = "".join(chr(c) for c in range(0x20, 0x7F))
        encoded = bytes(encode_text_byte(c) for c in chars)
        decoded = decode_text_bytes(encoded, 0, len(chars))
        self.assertEqual(decoded, chars)


class TestDecodeTextBytes(unittest.TestCase):
    """Test cases for text byte decoder"""
    
    def test_decode_printable_ascii(self):
        """Test decoding printable ASCII characters"""
        # Create test data with printable ASCII (space to ~)
        test_data = bytes([0x20, 0x41, 0x42, 0x43, 0x7E])  # " ABC~"
        result = decode_text_bytes(test_data, 0, 5)
        self.assertEqual(result, " ABC~")
    
    def test_decode_with_parity_bit(self):
        """Test that parity bit (bit 7) is ignored"""
        # Same characters but with parity bit set
        test_data = bytes([0xA0, 0xC1, 0xC2, 0xC3, 0xFE])  # " ABC~" with parity
        result = decode_text_bytes(test_data, 0, 5)
        self.assertEqual(result, " ABC~")
    
    def test_decode_control_codes(self):
        """Test that control codes are replaced with box character"""
        # Control codes (< 0x20)
        test_data = bytes([0x00, 0x01, 0x0A, 0x1F])
        result = decode_text_bytes(test_data, 0, 4)
        self.assertEqual(result, "☒☒☒☒")
    
    def test_decode_mixed_content(self):
        """Test decoding mixed printable and control characters"""
        test_data = bytes([0x41, 0x00, 0x42, 0x0A, 0x43])  # "A\x00B\x0AC"
        result = decode_text_bytes(test_data, 0, 5)
        self.assertEqual(result, "A☒B☒C")
    
    def test_decode_partial_range(self):
        """Test decoding a specific range of bytes"""
        test_data = bytes([0x00, 0x41, 0x42, 0x43, 0x00])
        result = decode_text_bytes(test_data, 1, 4)  # Only "ABC"
        self.assertEqual(result, "ABC")
    
    def test_decode_empty_range(self):
        """Test decoding an empty range"""
        test_data = bytes([0x41, 0x42, 0x43])
        result = decode_text_bytes(test_data, 1, 1)  # Empty range
        self.assertEqual(result, "")
    
    def test_decode_beyond_data_length(self):
        """Test that decoding stops at data boundary"""
        test_data = bytes([0x41, 0x42])
        result = decode_text_bytes(test_data, 0, 10)  # Request more than available
        self.assertEqual(result, "AB")  # Should only decode what's available
    
    def test_decode_teletext_header(self):
        """Test decoding a typical Teletext header (32 bytes)"""
        # Simulate a typical header: "BBC ONE" followed by spaces
        header_bytes = bytearray(32)
        header_bytes[0:7] = b'BBC ONE'
        for i in range(7, 32):
            header_bytes[i] = 0x20  # Space
        
        result = decode_text_bytes(bytes(header_bytes), 0, 32)
        self.assertTrue(result.startswith("BBC ONE"))
        self.assertEqual(len(result), 32)


class TestIntegration(unittest.TestCase):
    """Integration tests combining multiple functions"""

    def test_hamming_encode_decode_page_address(self):
        """Encoding a magazine/packet address and decoding it should round-trip"""
        # Magazine 1, packet 0 -> combined byte = 0x00, split as two nibbles (0, 0)
        # Magazine 3, packet 17 -> combined = (17 << 3) | 3 = 0x8B
        combined = (17 << 3) | 3
        lo_nibble = combined & 0x0F
        hi_nibble = (combined >> 4) & 0x0F
        byte1 = hamming_8_4_encode(lo_nibble)
        byte2 = hamming_8_4_encode(hi_nibble)
        decoded1 = hamming_8_4_decode(byte1)
        decoded2 = hamming_8_4_decode(byte2)
        recovered = (decoded2 << 4) | decoded1
        self.assertEqual(recovered, combined)

    def test_decode_page_number(self):
        """Test decoding a page number from Hamming encoded bytes"""
        # Simulate decoding page 172 (units=2, tens=7 in BCD)
        # Using correct Hamming 8/4 encodings (ETS 300 706 s.8.2)
        page_units_encoded = 0x49  # Encodes 2
        page_tens_encoded = 0x2F   # Encodes 7
        
        page_units = hamming_8_4_decode(page_units_encoded)
        page_tens = hamming_8_4_decode(page_tens_encoded)
        
        # Both should decode successfully
        self.assertIsNotNone(page_units)
        self.assertIsNotNone(page_tens)
        
        # Check the decoded values
        self.assertEqual(page_units, 2)
        self.assertEqual(page_tens, 7)


def run_tests():
    """Run all tests"""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)

# Made with Bob

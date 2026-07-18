#!/usr/bin/env python3
"""
Teletext Helper Functions

Common utility functions for processing Teletext data.
"""

def hamming_8_4_decode(byte):
    """
    Decode a Hamming 8/4 encoded byte according to Teletext specification.
    
    Bit numbering (LSB = bit 1):
    bit 1: P1 (parity)
    bit 2: D1 (data)
    bit 3: P2 (parity)
    bit 4: D2 (data)
    bit 5: P3 (parity)
    bit 6: D3 (data)
    bit 7: P4 (parity)
    bit 8: D4 (data)
    
    Parity formulas (ETS 300 706 s.8.2):
    P1 = 1 ⊕ D1 ⊕ D3 ⊕ D4
    P2 = 1 ⊕ D1 ⊕ D2 ⊕ D4
    P3 = 1 ⊕ D1 ⊕ D2 ⊕ D3
    P4 = 1 ⊕ P1 ⊕ D1 ⊕ P2 ⊕ D2 ⊕ P3 ⊕ D3 ⊕ D4
    
    Returns the decoded 4-bit value (D1 D2 D3 D4), or None if uncorrectable error.
    """
    # Extract bits (LSB = bit 1) - parity on odd bits, data on even bits
    p1 = (byte >> 0) & 1  # bit 1
    d1 = (byte >> 1) & 1  # bit 2
    p2 = (byte >> 2) & 1  # bit 3
    d2 = (byte >> 3) & 1  # bit 4
    p3 = (byte >> 4) & 1  # bit 5
    d3 = (byte >> 5) & 1  # bit 6
    p4 = (byte >> 6) & 1  # bit 7
    d4 = (byte >> 7) & 1  # bit 8
    
    # Calculate parity checks (ETS 300 706 s.8.2)
    # Test A: P1, D1, D3, D4
    c1 = 1 ^ p1 ^ d1 ^ d3 ^ d4
    
    # Test B: P2, D1, D2, D4
    c2 = 1 ^ p2 ^ d1 ^ d2 ^ d4
    
    # Test C: P3, D1, D2, D3
    c3 = 1 ^ p3 ^ d1 ^ d2 ^ d3
    
    # Test D: all 8 bits (overall parity)
    c4 = 1 ^ p4 ^ p1 ^ d1 ^ p2 ^ d2 ^ p3 ^ d3 ^ d4
    
    # Build syndrome from P1, P2, P3 checks
    syndrome = (c3 << 2) | (c2 << 1) | c1
    
    # If syndrome is 0 and P4 is OK, no error
    if syndrome == 0 and c4 == 0:
        # Return data bits: D1 is bit 0, D2 is bit 1, D3 is bit 2, D4 is bit 3
        return d1 | (d2 << 1) | (d3 << 2) | (d4 << 3)
    
    # If syndrome is 0 but P4 fails, it's an error in P4 itself (single bit error)
    # This is correctable - just ignore the P4 error and return the data
    if syndrome == 0 and c4 != 0:
        # Error in P4 bit - data bits are correct
        return d1 | (d2 << 1) | (d3 << 2) | (d4 << 3)
    
    # Single bit error correction
    # The syndrome indicates which bit position (0-7) is in error
    # Syndrome to erroneous bit position (0-based), derived from ETS 300 706 s.8.2
    syndrome_to_bit = {
        1: 0,  # P1
        7: 1,  # D1
        2: 2,  # P2
        6: 3,  # D2
        4: 4,  # P3
        5: 5,  # D3
        0: 6,  # P4 (only when c4=1)
        3: 7,  # D4
    }
    
    error_bit = syndrome_to_bit.get(syndrome, -1)
    
    # Correct the erroneous data bit if it is one of D1–D4
    if error_bit == 1:   # D1
        d1 ^= 1
    elif error_bit == 3: # D2
        d2 ^= 1
    elif error_bit == 5: # D3
        d3 ^= 1
    elif error_bit == 7: # D4
        d4 ^= 1
    # Parity bit errors (positions 0, 2, 4, 6) need no data correction
    
    # Return data bits: D1 is bit 0, D2 is bit 1, D3 is bit 2, D4 is bit 3
    return d1 | (d2 << 1) | (d3 << 2) | (d4 << 3)


def hamming_8_4_encode(value):
    """
    Encode a 4-bit value as a Hamming 8/4 byte for Teletext.

    Bit layout (LSB = bit 1):
      bit 1 (P1), bit 2 (D1), bit 3 (P2), bit 4 (D2),
      bit 5 (P3), bit 6 (D3), bit 7 (P4), bit 8 (D4)

    Args:
        value: integer 0-15

    Returns:
        int: encoded byte
    """
    d1 = (value >> 0) & 1
    d2 = (value >> 1) & 1
    d3 = (value >> 2) & 1
    d4 = (value >> 3) & 1

    p1 = 1 ^ d1 ^ d3 ^ d4
    p2 = 1 ^ d1 ^ d2 ^ d4
    p3 = 1 ^ d1 ^ d2 ^ d3
    p4 = 1 ^ p1 ^ d1 ^ p2 ^ d2 ^ p3 ^ d3 ^ d4

    return (p1 << 0) | (d1 << 1) | (p2 << 2) | (d2 << 3) | (p3 << 4) | (d3 << 5) | (p4 << 6) | (d4 << 7)


def encode_text_byte(char):
    """
    Encode a single ASCII character as a Teletext text byte with odd parity.

    Bit 7 is set so that the total number of 1-bits in the byte is odd.

    Args:
        char: a single character string (printable ASCII)

    Returns:
        int: encoded byte (7-bit ASCII value + odd parity in bit 7)
    """
    val = ord(char) & 0x7F
    # Count set bits in the 7 data bits
    ones = bin(val).count('1')
    # Set parity bit so total ones is odd
    parity = 0 if (ones % 2 == 1) else 1
    return val | (parity << 7)


def decode_text_bytes(data, start_byte, end_byte):
    """
    Decode text from Teletext data bytes.
    
    Each byte has 7 data bits and 1 odd parity bit (bit 7).
    Control codes are represented with a box character (☒).
    
    Args:
        data: bytes object containing the packet data
        start_byte: starting byte index (inclusive)
        end_byte: ending byte index (exclusive)
        
    Returns:
        str: decoded text
    """
    text = ""
    for i in range(start_byte, end_byte):
        if i >= len(data):
            break
        byte = data[i]
        # Extract lower 7 bits (data bits), ignore bit 7 (parity)
        char_code = byte & 0x7F
        # Convert to ASCII character
        if char_code >= 0x20 and char_code <= 0x7E:  # Printable ASCII range
            text += chr(char_code)
        else:
            text += '☒'  # Box with cross for control codes
    
    return text

# Made with Bob

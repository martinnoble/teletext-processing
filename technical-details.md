# Technical Details - T42 Teletext Format

Detailed technical information about the T42 Teletext format, Hamming encoding, and packet structure.

## T42 Format Overview

T42 is a Teletext packet format consisting of 42 bytes of data. This is the standard 45-byte Teletext transmission format without the first 3 bytes of clock run-in and framing code.

Each T42 packet contains:
- 2 bytes: Packet header (Hamming 8/4 encoded)
- 40 bytes: Packet data (content varies by packet type)

## Hamming 8/4 Encoding

The Hamming 8/4 encoding scheme protects 4 data bits with 4 parity bits, enabling single-bit error correction and some double-bit error detection.

### Bit Layout

```
Bit positions: P1 D1 P2 D2 P3 D3 P4 D4
               1  2  3  4  5  6  7  8
```

Where:
- **P1, P2, P3, P4** are parity bits
- **D1, D2, D3, D4** are data bits

### Parity Formulas

The parity bits are calculated using odd parity:

```
P1 = 1 ⊕ D1 ⊕ D3 ⊕ D4
P2 = 1 ⊕ D1 ⊕ D2 ⊕ D4
P3 = 1 ⊕ D1 ⊕ D2 ⊕ D3
P4 = 1 ⊕ P1 ⊕ D1 ⊕ P2 ⊕ D2 ⊕ P3 ⊕ D3 ⊕ D4
```

### Correct Encodings Table

| Value | Encoding | Value | Encoding |
|-------|----------|-------|----------|
| 0x0   | 0x15     | 0x8   | 0xD0     |
| 0x1   | 0x02     | 0x9   | 0xC7     |
| 0x2   | 0x49     | 0xA   | 0x8C     |
| 0x3   | 0x5E     | 0xB   | 0x9B     |
| 0x4   | 0x64     | 0xC   | 0xA1     |
| 0x5   | 0x73     | 0xD   | 0xB6     |
| 0x6   | 0x38     | 0xE   | 0xFD     |
| 0x7   | 0x2F     | 0xF   | 0xEA     |

### Error Correction Capabilities

The Hamming 8/4 decoder can:
- **Correct** any single-bit error
- **Detect** some double-bit errors (but not all)
- Return `None` for uncorrectable errors

### Syndrome-to-Bit Mapping

When an error is detected, the syndrome value indicates which bit position is in error:

| Syndrome | Bit Position | Bit Name |
|----------|--------------|----------|
| 0 (c4=1) | 6            | P4       |
| 1        | 0            | P1       |
| 2        | 2            | P2       |
| 3        | 7            | D4       |
| 4        | 4            | P3       |
| 5        | 5            | D3       |
| 6        | 3            | D2       |
| 7        | 1            | D1       |

## Packet Structure

### Packet Header (Bytes 0-1)

The first two bytes of each packet are Hamming 8/4 encoded and contain addressing information:

**Byte 0 (First Hamming byte):**
- Bits 0-2: Magazine number (0-7, where 0 represents magazine 8)
- Bit 3: Packet number bit 0

**Byte 1 (Second Hamming byte):**
- Bits 0-3: Packet number bits 1-4

Combined, these provide:
- **Magazine number**: 1-8
- **Packet number**: 0-31

### Page Header (Packet 0)

Page header packets (packet number 0) contain 40 bytes of data:

**Bytes 0-1: Page Number (BCD encoded)**
- Units and tens of page number
- Each nibble represents one decimal digit

**Bytes 2-9: Sub-code (8 bytes)**
- Additional page identification
- Control bits for page attributes

**Bytes 10-41: Header Text (32 bytes)**
- Display text for the page header row
- 7-bit ASCII with parity bit
- Often contains page title and time

### Data Packets (Packets 1-31)

Data packets contain 40 bytes of text data:

**Bytes 0-39: Text Data**
- 7-bit ASCII characters with parity bit (bit 7)
- Represents one row of Teletext display
- May contain control codes for colors, graphics, etc.

## Text Encoding

Teletext text uses 7-bit ASCII with an 8th parity bit:

- **Bits 0-6**: ASCII character code
- **Bit 7**: Odd parity bit

### Special Characters

- **0x00-0x1F**: Control codes (colors, graphics modes, etc.)
- **0x20-0x7F**: Printable ASCII characters
- Parity bit is stripped during decoding

## BCD Encoding

Page numbers use Binary-Coded Decimal (BCD) encoding:

- Each nibble (4 bits) represents one decimal digit (0-9)
- Example: Page 123 is encoded as 0x23 0x01
  - Low byte: 0x23 (2 in high nibble, 3 in low nibble)
  - High byte: 0x01 (0 in high nibble, 1 in low nibble)

## References

This implementation follows the [ETS 300 706 Enhanced Teletext specification](https://www.etsi.org/deliver/etsi_i_ets/300700_300799/300706/01_60/ets_300706e01p.pdf).

## See Also

- [t42parser.md](t42parser.md) - Parse and analyze T42 files
- [t42restream.md](t42restream.md) - Live restreaming with time injection
- [README.md](README.md) - Project overview


# Useful resources

T42 archive: https://computer-legacy.com/teletext.html


# T42 Teletext Parser

A Python library for processing T42 Teletext packet streams with Hamming 8/4 error correction.

## Overview

This project provides tools to decode T42 format Teletext packets, which consist of 42 bytes of data (the standard 45-byte Teletext transmission format without the first 3 bytes of clock run-in and framing).

Error correction implementation follows the [ETS 300 706 Enhanced Teletext specification](https://github.com/martinnoble/teletext-processing/blob/main/ets_300706e01p.pdf)

## Features

- **Hamming 8/4 Decoder**: Decodes Hamming 8/4 encoded bytes with single-bit error correction
- **Packet Header Parser**: Extracts magazine number and packet number from packet headers
- **Page Header Decoder**: Decodes page numbers, sub-codes, control bits, and header text
- **Data Packet Decoder**: Extracts text content from data packets
- **Filtering**: Filter by magazine and/or page number
- **Statistics Mode**: Analyze packet counts per page with anomaly detection
- **Comprehensive Tests**: 21 unit tests covering all helper functionality

## Project Structure

```
t42parser/
├── README.md                # This file
├── teletext_helpers.py      # Reusable helper library
├── test_teletext_helpers.py # Unit tests (21 tests, all passing)
├── t42parser.py             # Main parser script
└── t42restream.py           # Restreamer script (live time injection)
```

## Installation

No external dependencies required - uses only Python standard library.

```bash
git clone <repository-url>
cd t42parser
```

## Usage

### Basic Usage

Process a T42 binary file:

```bash
python3 t42parser.py input.t42
```

### Filter by Magazine

```bash
python3 t42parser.py input.t42 --magazine 1
```

### Filter by Page

```bash
python3 t42parser.py input.t42 --page 100
```

### Statistics Mode

Analyze packet counts per page and detect anomalies:

```bash
python3 t42parser.py input.t42 --stats
```

### Using the Helper Library

```python
from teletext_helpers import hamming_8_4_decode, decode_text_bytes

# Decode a Hamming 8/4 encoded byte
value = hamming_8_4_decode(0x15)  # Returns 0

# Decode text from Teletext data
data = b'\x48\x65\x6c\x6c\x6f'
text = decode_text_bytes(data, 0, 5)  # Returns "Hello"
```

## Hamming 8/4 Encoding

The Hamming 8/4 encoding uses odd parity with the following bit layout:

```
Bit positions: P1 D1 P2 D2 P3 D3 P4 D4
               1  2  3  4  5  6  7  8
```

Where:
- P1, P2, P3, P4 are parity bits
- D1, D2, D3, D4 are data bits

### Parity Formulas

```
P1 = 1 ⊕ D1 ⊕ D3 ⊕ D4
P2 = 1 ⊕ D1 ⊕ D2 ⊕ D4
P3 = 1 ⊕ D1 ⊕ D2 ⊕ D3
P4 = 1 ⊕ P1 ⊕ D1 ⊕ P2 ⊕ D2 ⊕ P3 ⊕ D3 ⊕ D4
```

### Correct Encodings

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

## Packet Structure

### Packet Header (First 2 bytes)

The first two bytes of each packet are Hamming 8/4 encoded and contain:
- **Magazine number**: Bits 0-2 of decoded value (values 0-7, where 0 represents magazine 8)
- **Packet number**: Bits 3-7 of decoded value (values 0-31)

### Page Header (Packet 0)

Contains:
- Page number (2 bytes, BCD encoded)
- Sub-code (8 bytes)
- Control bits
- Header text (32 bytes)

### Data Packets (Packets 1-31)

Contains 40 bytes of text data with 7-bit ASCII + parity.

## Testing

Run the comprehensive test suite:

```bash
python3 test_teletext_helpers.py
```

All 21 tests should pass:
- ✅ Valid Hamming decode (no errors)
- ✅ Single-bit error correction (all 8 bit positions)
- ✅ All 16 nibble values (0x0-0xF)
- ✅ Text decoding (printable ASCII, control codes, parity bits)
- ✅ Integration tests (page number decoding)

## Technical Details

### Error Correction

The Hamming 8/4 decoder can:
- **Correct** any single-bit error
- **Detect** some double-bit errors (but not all)
- Return `None` for uncorrectable errors

### Syndrome-to-Bit Mapping

When an error is detected, the syndrome value indicates which bit is in error:

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

## t42restream

`t42restream.py` reads a T42 packet stream and writes it to stdout, replacing the time field in every page-header packet with the current wall-clock time. It is designed to feed live output into a Teletext encoder or downstream tool.

### Basic Usage

```bash
python3 t42restream.py input.t42
```

### Loop Continuously

```bash
python3 t42restream.py input.t42 --loop
```

### Custom Time Mask

The `--mask` option controls which of the 32 header-text columns are overwritten with the formatted time. Use `#` for positions that should receive time characters and `?` to leave the original byte intact.

```bash
# Replace the last 8 columns with HH:MM:SS
python3 t42restream.py input.t42 --mask "????????????????????????########"

# Replace columns 0-7 with HH:MM:SS
python3 t42restream.py input.t42 --mask "########????????????????????????????????"
```

The number of `#` characters must exactly match the length of the string produced by `--time-format`.

### Custom Time Format

```bash
python3 t42restream.py input.t42 --time-format "%d/%m %H:%M" --mask "??????????##########"
```

### Filter by Magazine or Page

```bash
# Only stream magazine 1
python3 t42restream.py input.t42 --magazine 1

# Only stream page 100 (hex page identifier, e.g. '1BA' for magazine 1, page BA)
python3 t42restream.py input.t42 --page 100
```

When `--page` is supplied without `--magazine`, the magazine is inferred from the page prefix.

### Interleave Mode

Re-orders the output stream so that pages from different magazines are emitted in round-robin order rather than in file order. Each complete page (header packet plus all following row packets) is treated as one unit. Incompatible with `--magazine` / `--page` filters.

```bash
python3 t42restream.py input.t42 --interleave --loop
```

### All Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mask MASK` | `"????????????????????????########"` | 32-char mask; `#` = time char, `?` = keep original |
| `--time-format FMT` | `"%H:%M:%S"` | strftime format string |
| `--loop` | off | Restart from the beginning of the file after reaching EOF |
| `--magazine MAG` | none | Only emit packets from this magazine (1–8) |
| `--page PAGE` | none | Only emit packets for this page (e.g. `100`, `1BA`) |
| `--interleave` | off | Round-robin pages across magazines before output |

## References

- [ETS 300 706 - Enhanced Teletext specification](https://www.etsi.org/deliver/etsi_i_ets/300700_300799/300706/01_60/ets_300706e01p.pdf)
- [Computer Legacy - Teletext T42 archive](https://computer-legacy.com/teletext.html)

## License

This project is provided as-is for educational and research purposes.

## Author

Created by Martin Noble with assistance from IBM Bob / Claude (Anthropic)
# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

**T42 Teletext Parser** is a Python library and toolset for processing T42 Teletext packet streams with Hamming 8/4 error correction. The project provides tools to decode, analyze, and restream archived Teletext broadcasts from the 1980s-1990s.

### Core Purpose

- Parse and decode T42 format Teletext packets (42-byte packets from the standard 45-byte format)
- Implement Hamming 8/4 single-bit error correction per ETS 300 706 specification
- Extract magazine numbers, page numbers, sub-codes, and text content
- Provide statistical analysis of packet streams with anomaly detection
- Enable live restreaming of archived content with real-time clock injection

### Key Technologies

- **Language**: Python 3 (standard library only, no external dependencies)
- **Domain**: Teletext broadcast data processing, error correction coding
- **Standards**: ETS 300 706 Enhanced Teletext specification

## Architecture

### Core Components

1. **teletext_helpers.py** - Reusable library module
   - Hamming 8/4 encoding/decoding with single-bit error correction
   - Text byte encoding/decoding with odd parity checking
   - Page CRC calculation (16-bit LFSR-based checksum)
   - Pure functions with no side effects

2. **t42parser.py** - Analysis and parsing tool
   - Packet header parsing (magazine/packet number extraction)
   - Page header decoding (page number, sub-code, control bits, header text)
   - Data packet text extraction with parity error detection
   - Packet X/27 (page links) decoding with CRC verification
   - Statistical analysis mode with deviation detection
   - Packet comparison utility

3. **t42restream.py** - Live restreaming tool
   - Real-time clock injection into page headers
   - Multiple streaming modes: sequential, interleaved, magazine-parallel
   - VBI line simulation for realistic broadcast timing
   - Control bit override capability
   - Looping support for continuous streams

### Data Flow

```
T42 Binary File (42-byte packets)
    ↓
Packet Header Parsing (Hamming 8/4 decode)
    ↓
Magazine/Packet Number Extraction
    ↓
Packet Type Routing:
    - Packet 0 → Page Header (page number, sub-code, control bits, header text)
    - Packets 1-24 → Data Rows (text content with parity checking)
    - Packet 27 → Page Links (editorial linking, CRC verification)
    ↓
Output: Decoded text, statistics, or restreamed packets
```

## Building and Running

### Prerequisites

- Python 3.6 or later
- No external dependencies required

### Running the Parser

```bash
# Basic parsing - show all packets
python3 t42parser.py input.t42

# Filter by magazine
python3 t42parser.py input.t42 --magazine 1

# Filter by page and decode text
python3 t42parser.py input.t42 --page 172 --decode-data

# Statistical analysis
python3 t42parser.py input.t42 --stats

# Show only pages with anomalies
python3 t42parser.py input.t42 --stats --deviations-only

# Compare two packets
python3 t42parser.py input.t42 --compare 100 200
```

### Running the Restreamer

```bash
# Basic restreaming with time injection
python3 t42restream.py input.t42 > output.t42

# Loop continuously
python3 t42restream.py input.t42 --loop

# Custom time format and position
python3 t42restream.py input.t42 --mask "????????????????????????????????" --time-format "%H:%M:%S"

# Interleaved magazine output
python3 t42restream.py input.t42 --interleave --vbi-lines 8

# Magazine-parallel scheduling
python3 t42restream.py input.t42 --magazine-parallel --vbi-lines 8

# Override control bits
python3 t42restream.py input.t42 --control subtitle=on --control update=off
```

### Running Tests

```bash
# Run all unit tests
python3 test_teletext_helpers.py

# Run with verbose output
python3 test_teletext_helpers.py -v

# Run specific test
python3 -m unittest test_teletext_helpers.TestHamming84Decode.test_correct_encodings
```

## Development Conventions

### Code Style

- **Docstrings**: All public functions have comprehensive docstrings with Args/Returns sections
- **Type hints**: Not used (Python 3.5 compatibility maintained)
- **Naming**: Snake_case for functions/variables, UPPER_CASE for constants
- **Line length**: Generally kept under 100 characters for readability
- **Comments**: Inline comments explain domain-specific logic (Hamming encoding, bit positions)

### Error Handling

- **Hamming decode failures**: Return `None` for uncorrectable errors
- **Packet parsing**: Gracefully handle malformed packets, continue processing
- **File I/O**: Catch `FileNotFoundError` and provide user-friendly error messages
- **Validation**: Validate command-line arguments before processing

### Testing Practices

- **Unit tests**: 21 comprehensive tests in `test_teletext_helpers.py`
- **Coverage**: All Hamming encoding/decoding paths tested
- **Test data**: Uses known-good encodings from ETS 300 706 specification
- **Edge cases**: Tests single-bit errors, double-bit errors, parity failures

### Domain-Specific Patterns

1. **Hamming 8/4 Encoding**
   - Bit numbering is 1-based (LSB = bit 1) per specification
   - Parity bits on odd positions (1,3,5,7), data bits on even positions (2,4,6,8)
   - Syndrome calculation identifies error bit position
   - Single-bit errors correctable, some double-bit errors detectable

2. **Packet Structure**
   - First 2 bytes: Hamming-encoded packet address (magazine + packet number)
   - Magazine 0 represents magazine 8
   - Packet 0 is page header, packets 1-24 are data rows, packet 27 is page links

3. **Text Encoding**
   - 7-bit ASCII with bit 7 as odd parity
   - Control codes (0x00-0x1F) displayed as ☒ character
   - Parity errors tracked per column for debugging

4. **Page CRC**
   - 16-bit LFSR with taps at stages 7, 9, 12, 16
   - Calculated over header text (bytes 10-33 of packet 0) and all data rows (bytes 2-41 of packets 1-25)
   - Missing packets treated as all-space (0x20)

## Important Technical Details

### T42 Format

- **Packet size**: 42 bytes (45-byte Teletext format minus 3-byte clock run-in/framing)
- **Byte 0-1**: Packet address (Hamming 8/4 encoded)
- **Byte 2-41**: Packet data (varies by packet type)

### Hamming 8/4 Syndrome Table

| Syndrome | Error Bit | Bit Name |
|----------|-----------|----------|
| 0 (c4=1) | 6         | P4       |
| 1        | 0         | P1       |
| 2        | 2         | P2       |
| 3        | 7         | D4       |
| 4        | 4         | P3       |
| 5        | 5         | D3       |
| 6        | 3         | D2       |
| 7        | 1         | D1       |

### Page Header Structure (Packet 0)

- **Bytes 2-3**: Page number (Hamming 8/4, BCD encoded)
- **Bytes 4-9**: Sub-code and control bits (Hamming 8/4)
  - S1-S4: 13-bit sub-code
  - C4-C11: Control bits (Erase, Newsflash, Subtitle, etc.)
- **Bytes 10-41**: Header text (32 characters, 7-bit ASCII + parity)

### Restreaming Modes

1. **Sequential**: Packets emitted in file order with time injection
2. **Interleaved**: Pages from different magazines round-robin, headers at field boundaries
3. **Magazine-parallel**: Deficit round-robin scheduling, bandwidth proportional to page count

## Common Tasks

### Adding a New Packet Type Decoder

1. Add decoding function to `t42parser.py` following pattern of `decode_page_header()` or `decode_packet_27()`
2. Use `hamming_8_4_decode()` for Hamming-encoded bytes
3. Use `decode_text_bytes()` for text content
4. Return structured data (tuple or dict) with `None` for decode failures
5. Add test cases to `test_teletext_helpers.py` if adding to library

### Modifying Time Injection

1. Edit `_apply_time_to_header()` in `t42restream.py`
2. Mask format: `#` = replace with time, `?` = preserve original
3. Time format uses Python `strftime()` format codes
4. Ensure formatted time length matches `#` count in mask

### Adding Statistical Analysis

1. Extend `analyze_page_statistics()` in `t42parser.py`
2. Track per-page metrics in `page_appearances` dict
3. Calculate statistics (mean, std dev) over all appearances
4. Flag deviations using threshold (default: 2σ)

## Resources

- **T42 Archive**: [computer-legacy.com/teletext.html](https://computer-legacy.com/teletext.html)
- **ETS 300 706 Specification**: Included as `ets_300706e01p.pdf`
- **Technical Details**: See `technical-details.md` for Hamming encoding details
- **Parser Documentation**: See `t42parser.md` for usage examples
- **Restreamer Documentation**: See `t42restream.md` for streaming modes

## Notes for AI Agents

- **Bit numbering**: Always use 1-based indexing when working with Hamming code (LSB = bit 1)
- **Magazine 0 = 8**: Remember this mapping when parsing packet addresses
- **Error correction**: Single-bit errors are correctable, double-bit errors may be undetectable
- **Parity checking**: Text bytes use odd parity (total set bits must be odd)
- **File format**: Binary files, 42 bytes per packet, no delimiters or headers
- **Testing**: Always run `test_teletext_helpers.py` after modifying core library functions
- **Performance**: No optimization needed - files are small (typically <10MB), processing is fast
- **Python version**: Code maintains Python 3.5+ compatibility (no f-strings, no type hints)

## Author Attribution

Created by Martin Noble with assistance from IBM Bob / Claude (Anthropic). All files end with comment `# Made with Bob`.

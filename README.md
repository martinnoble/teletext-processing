# T42 Teletext Parser

A Python library and toolset for processing T42 Teletext packet streams with Hamming 8/4 error correction.

## Quick Links

- **[t42parser.md](t42parser.md)** - Parse and analyze T42 files
- **[t42restream.md](t42restream.md)** - Live restreaming with time injection
- **[technical-details.md](technical-details.md)** - Hamming encoding and packet structure

## Overview

This project provides tools to decode T42 format Teletext packets, which consist of 42 bytes of data (the standard 45-byte Teletext transmission format without the first 3 bytes of clock run-in and framing).

Error correction implementation follows the [ETS 300 706 Enhanced Teletext specification](https://github.com/martinnoble/teletext-processing/blob/main/ets_300706e01p.pdf).

## Features

- **Hamming 8/4 Decoder**: Single-bit error correction
- **Packet Parsing**: Magazine, page, and packet number extraction
- **Text Decoding**: Page headers and data packets
- **Filtering**: By magazine and/or page number
- **Statistics**: Packet count analysis with anomaly detection
- **Live Restreaming**: Time injection for archived streams
- **Comprehensive Tests**: 21 unit tests covering all functionality

## Installation

No external dependencies required - uses only Python standard library.

```bash
git clone <repository-url>
cd t42parser
```

## Quick Start

### Parse a T42 file

```bash
python3 t42parser.py input.t42
```

### Stream with live time injection

```bash
python3 t42restream.py input.t42 --loop
```

### Run tests

```bash
python3 test_teletext_helpers.py
```

## Project Structure

```
t42parser/
├── README.md                # This file - project overview
├── t42parser.md             # Detailed parser documentation
├── t42restream.md           # Detailed restreamer documentation
├── technical-details.md     # Technical specification
├── teletext_helpers.py      # Reusable helper library
├── test_teletext_helpers.py # Unit tests (21 tests)
├── t42parser.py             # Main parser script
└── t42restream.py           # Restreamer script
```

## Documentation

### [t42parser.md](t42parser.md)
Complete guide to using `t42parser.py`:
- Command-line options
- Filtering by magazine and page
- Statistics mode
- Output format
- Usage examples

### [t42restream.md](t42restream.md)
Complete guide to using `t42restream.py`:
- Live time injection
- Custom time formats and masks
- Looping and filtering
- Interleave mode
- Use cases and examples

### [technical-details.md](technical-details.md)
Technical specification covering:
- T42 format structure
- Hamming 8/4 encoding
- Error correction algorithms
- Packet structure
- Text and BCD encoding

## Resources

- **T42 Archive**: [computer-legacy.com/teletext.html](https://computer-legacy.com/teletext.html)
- **ETS 300 706 Specification**: [ETSI Enhanced Teletext](https://www.etsi.org/deliver/etsi_i_ets/300700_300799/300706/01_60/ets_300706e01p.pdf)

## License

This project is provided as-is for educational and research purposes.

## Author

Created by Martin Noble with assistance from IBM Bob / Claude (Anthropic)
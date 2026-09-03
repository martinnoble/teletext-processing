# t42parser.py - T42 Teletext Parser

A command-line tool for processing T42 Teletext packet streams with filtering and analysis capabilities.

## Overview

`t42parser.py` is the main parser script that reads T42 binary files and outputs decoded Teletext packets. It supports filtering by magazine and page number, as well as statistical analysis of packet distributions.

## Basic Usage

Process a T42 binary file:

```bash
python3 t42parser.py input.t42
```

This will output all decoded packets to stdout.

## Command-Line Options

### Filter by Magazine

Filter packets to show only those from a specific magazine (1-8):

```bash
python3 t42parser.py input.t42 --magazine 1
```

### Filter by Page

Filter packets to show only those for a specific page number:

```bash
python3 t42parser.py input.t42 --page 100
```

Page numbers are specified in decimal format (e.g., 100, 200, 888).

### Statistics Mode

Analyze packet counts per page and detect anomalies:

```bash
python3 t42parser.py input.t42 --stats
```

Statistics mode provides:
- Total packet count per page
- Distribution analysis
- Anomaly detection for pages with unusual packet counts

## Using the Helper Library

The parser is built on top of `teletext_helpers.py`, which provides reusable functions:

```python
from teletext_helpers import hamming_8_4_decode, decode_text_bytes

# Decode a Hamming 8/4 encoded byte
value = hamming_8_4_decode(0x15)  # Returns 0

# Decode text from Teletext data
data = b'\x48\x65\x6c\x6c\x6f'
text = decode_text_bytes(data, 0, 5)  # Returns "Hello"
```

## Output Format

The parser outputs decoded packet information including:
- Magazine number
- Packet number
- Page number (for page headers)
- Decoded text content
- Control bits and sub-codes (for page headers)

## Examples

### View all packets from magazine 8

```bash
python3 t42parser.py BBC2-19840529-sq.t42 --magazine 8
```

### Analyze page distribution

```bash
python3 t42parser.py ITV-19890114-sq.t42 --stats
```

### Extract a specific page

```bash
python3 t42parser.py BBC1-19940218-sq.t42 --page 888
```

## See Also

- [t42restream.md](t42restream.md) - Live restreaming with time injection
- [technical-details.md](technical-details.md) - Hamming encoding and packet structure
- [README.md](README.md) - Project overview

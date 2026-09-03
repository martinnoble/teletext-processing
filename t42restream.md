# t42restream.py - T42 Teletext Restreamer

A command-line tool that reads T42 packet streams and writes them to stdout with live time injection into page headers.

## Overview

`t42restream.py` is designed to feed live output into a Teletext encoder or downstream tool. It replaces the time field in every page-header packet with the current wall-clock time, making archived Teletext streams appear live.

## Basic Usage

Stream a T42 file with live time injection:

```bash
python3 t42restream.py input.t42
```

Output is written to stdout and can be piped to other tools:

```bash
python3 t42restream.py input.t42 > output.t42
```

## Command-Line Options

### Loop Continuously

Restart from the beginning of the file after reaching EOF:

```bash
python3 t42restream.py input.t42 --loop
```

This is useful for continuous streaming applications.

### Custom Time Mask

The `--mask` option controls which of the 32 header-text columns are overwritten with the formatted time. Use `#` for positions that should receive time characters and `?` to leave the original byte intact.

**Default mask:** `"????????????????????????########"` (replaces last 8 columns with HH:MM:SS)

```bash
# Replace the last 8 columns with HH:MM:SS
python3 t42restream.py input.t42 --mask "????????????????????????########"

# Replace columns 0-7 with HH:MM:SS
python3 t42restream.py input.t42 --mask "########????????????????????????????????"

# Replace middle section
python3 t42restream.py input.t42 --mask "????????????########????????????"
```

**Important:** The number of `#` characters must exactly match the length of the string produced by `--time-format`.

### Custom Time Format

Specify a custom time format using Python's strftime format codes:

```bash
# Date and time: DD/MM HH:MM
python3 t42restream.py input.t42 --time-format "%d/%m %H:%M" --mask "??????????##########"

# 12-hour format with AM/PM
python3 t42restream.py input.t42 --time-format "%I:%M %p" --mask "????????????????????????########"

# Full date and time
python3 t42restream.py input.t42 --time-format "%Y-%m-%d %H:%M:%S" --mask "???????????????###################"
```

**Default format:** `"%H:%M:%S"` (24-hour time)

### Filter by Magazine

Only stream packets from a specific magazine (1-8):

```bash
python3 t42restream.py input.t42 --magazine 1
```

### Filter by Page

Only stream packets for a specific page:

```bash
# Decimal page number
python3 t42restream.py input.t42 --page 100

# Hex page identifier (magazine 1, page BA)
python3 t42restream.py input.t42 --page 1BA
```

When `--page` is supplied without `--magazine`, the magazine is inferred from the page prefix.

### Interleave Mode

Re-orders the output stream so that pages from different magazines are emitted in round-robin order rather than in file order. Each complete page (header packet plus all following row packets) is treated as one unit.

```bash
python3 t42restream.py input.t42 --interleave --loop
```

**Note:** Interleave mode is incompatible with `--magazine` and `--page` filters.

## Complete Options Reference

| Option | Default | Description |
|--------|---------|-------------|
| `--mask MASK` | `"????????????????????????########"` | 32-character mask; `#` = time char, `?` = keep original |
| `--time-format FMT` | `"%H:%M:%S"` | strftime format string for time display |
| `--loop` | off | Restart from the beginning of the file after reaching EOF |
| `--magazine MAG` | none | Only emit packets from this magazine (1–8) |
| `--page PAGE` | none | Only emit packets for this page (e.g. `100`, `1BA`) |
| `--interleave` | off | Round-robin pages across magazines before output |

## Examples

### Basic live streaming

```bash
python3 t42restream.py BBC2-19840529-sq.t42 --loop
```

### Stream with custom time position

```bash
python3 t42restream.py ITV-19890114-sq.t42 --mask "########????????????????????????????????" --loop
```

### Stream specific magazine with date/time

```bash
python3 t42restream.py BBC1-19940218-sq.t42 --magazine 8 --time-format "%d/%m %H:%M" --mask "??????????##########" --loop
```

### Interleaved multi-magazine stream

```bash
python3 t42restream.py input.t42 --interleave --loop
```

## Use Cases

- **Live Teletext Encoding:** Feed into hardware or software Teletext encoders
- **Testing:** Simulate live Teletext broadcasts for testing purposes
- **Archival Playback:** Make archived Teletext content appear current
- **Multi-Magazine Balancing:** Use interleave mode to ensure fair distribution across magazines

## See Also

- [t42parser.md](t42parser.md) - Parse and analyze T42 files
- [technical-details.md](technical-details.md) - Hamming encoding and packet structure
- [README.md](README.md) - Project overview

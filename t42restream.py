#!/usr/bin/env python3
"""
T42 Teletext Restreamer

Reads a T42 teletext packet stream file and writes it to stdout with the
time field in every page-header packet replaced with the current wall-clock
time.

Usage:
    python t42restream.py <input_file> [options]

Options:
    --mask MASK         32-character mask string for the header text region
                        (columns 8-39 of the display row).
                        Use '#' to mark positions that should be replaced with
                        the formatted time, '?' to leave the original byte
                        unchanged.
                        Default: "????????????????????????????????" with the last
                        8 positions as '#' (i.e. "????????????????????????########")
    --time-format FMT   strftime format string for the time text that fills the
                        '#' positions.  The rendered string must be exactly as
                        long as the number of '#' characters in the mask.
                        Default: "%H:%M:%S"
    --loop              Loop through the file indefinitely (streams continuously).
    --magazine MAG      Only stream packets from this magazine number (1-8).
    --page PAGE         Only stream packets for this page number (e.g. 172, 1BA).
                        Implies --magazine is set to the magazine of that page if
                        --magazine is not supplied explicitly.
"""

import sys
import os
import datetime

from teletext_helpers import hamming_8_4_decode, encode_text_byte

PACKET_SIZE = 42
# Header text occupies packet bytes 10-41 (32 characters shown on screen)
HEADER_TEXT_START = 10
HEADER_TEXT_LEN = 32

DEFAULT_MASK = "?" * 24 + "########"
DEFAULT_TIME_FORMAT = "%H:%M:%S"


def _parse_packet_address(packet_data):
    """Return (magazine, packet_number) or (None, None) on error."""
    if len(packet_data) < 2:
        return None, None
    decoded1 = hamming_8_4_decode(packet_data[0])
    decoded2 = hamming_8_4_decode(packet_data[1])
    if decoded1 is None or decoded2 is None:
        return None, None
    combined = (decoded2 << 4) | decoded1
    magazine = combined & 0x07
    if magazine == 0:
        magazine = 8
    packet_number = (combined >> 3) & 0x1F
    return magazine, packet_number


def _parse_page_hex(packet_data, magazine):
    """
    Return the page identifier string (e.g. '172') for a header packet,
    or None if the page bytes cannot be decoded.
    Requires packet_data to be a full PACKET_SIZE-byte header packet.
    """
    page_units = hamming_8_4_decode(packet_data[2])
    page_tens = hamming_8_4_decode(packet_data[3])
    if page_units is None or page_tens is None:
        return None
    return f"{magazine:X}{page_tens:X}{page_units:X}"


def _apply_time_to_header(packet_data, mask, time_format):
    """
    Return a modified copy of *packet_data* with the '#'-masked header
    positions replaced by the current time formatted with *time_format*.
    Positions marked '?' are left unchanged.

    Args:
        packet_data: bytes, exactly PACKET_SIZE bytes long
        mask: str, exactly HEADER_TEXT_LEN characters;
              '#' marks positions to replace, '?' leaves original byte
        time_format: strftime format string; rendered string length must equal
                     the number of '#' characters in the mask

    Returns:
        bytes: modified packet
    """
    now = datetime.datetime.now()
    time_str = now.strftime(time_format)

    hash_count = mask.count('#')
    if len(time_str) != hash_count:
        raise ValueError(
            f"Formatted time '{time_str}' has {len(time_str)} characters but "
            f"mask has {hash_count} '#' positions — they must match."
        )

    packet = bytearray(packet_data)
    time_index = 0
    for i, ch in enumerate(mask):
        if ch == '#':
            byte_pos = HEADER_TEXT_START + i
            packet[byte_pos] = encode_text_byte(time_str[time_index])
            time_index += 1

    return bytes(packet)


def restream(input_file, mask, time_format, loop, output=None,
             filter_magazine=None, filter_page=None):
    """
    Read *input_file* packet-by-packet and write every packet to *output*
    (defaults to sys.stdout.buffer), rewriting header packets with the
    current time according to *mask* and *time_format*.

    Args:
        input_file: path to the T42 file
        mask: 32-character mask string ('#' = replace with time character,
              '?' = leave unchanged)
        time_format: strftime format string
        loop: if True, seek back to the start of the file after reaching EOF
        output: writable binary stream; defaults to sys.stdout.buffer
        filter_magazine: if not None, only emit packets from this magazine (1-8)
        filter_page: if not None, only emit packets for this page (e.g. '172')
    """
    if len(mask) != HEADER_TEXT_LEN:
        raise ValueError(
            f"Mask must be exactly {HEADER_TEXT_LEN} characters long (got {len(mask)})."
        )

    if output is None:
        output = sys.stdout.buffer

    # Normalise filter_page to uppercase for comparison
    filter_page_upper = filter_page.upper() if filter_page is not None else None

    # When filtering by page, derive the magazine from the page prefix so that
    # inter-magazine packets are also suppressed correctly.
    if filter_page_upper is not None and filter_magazine is None:
        try:
            filter_magazine = int(filter_page_upper[0], 16)
            if filter_magazine == 0:
                filter_magazine = 8
        except (ValueError, IndexError):
            pass

    current_page_matches = True  # True when no page filter is active

    with open(input_file, 'rb') as f:
        while True:
            packet = f.read(PACKET_SIZE)

            if len(packet) == 0:
                if loop:
                    f.seek(0)
                    current_page_matches = filter_page_upper is None
                    continue
                break

            if len(packet) < PACKET_SIZE:
                # Incomplete trailing packet — skip and optionally loop
                if loop:
                    f.seek(0)
                    current_page_matches = filter_page_upper is None
                    continue
                break

            magazine, packet_number = _parse_packet_address(packet)

            if magazine is None:
                # Undecodable address — drop when any filter is active
                if filter_magazine is None and filter_page_upper is None:
                    output.write(packet)
                    output.flush()
                continue

            # Magazine filter
            if filter_magazine is not None and magazine != filter_magazine:
                if packet_number == 0:
                    current_page_matches = False
                continue

            if packet_number == 0:
                # Header packet — determine whether this page passes the filter
                if filter_page_upper is not None:
                    page_hex = _parse_page_hex(packet, magazine)
                    current_page_matches = (page_hex == filter_page_upper)
                else:
                    current_page_matches = True

                if current_page_matches:
                    # Inject current time into header
                    packet = _apply_time_to_header(packet, mask, time_format)
                else:
                    #ensure we don't output non matching header packets
                    continue
            else:
                # Non-header packet — emit only if we are inside a matching page
                if not current_page_matches:
                    continue

            output.write(packet)
            output.flush()


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    mask = DEFAULT_MASK
    time_format = DEFAULT_TIME_FORMAT
    loop = False
    filter_magazine = None
    filter_page = None

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--mask":
            if i + 1 >= len(sys.argv):
                print("Error: --mask requires an argument", file=sys.stderr)
                sys.exit(1)
            mask = sys.argv[i + 1]
            i += 2
        elif arg == "--time-format":
            if i + 1 >= len(sys.argv):
                print("Error: --time-format requires an argument", file=sys.stderr)
                sys.exit(1)
            time_format = sys.argv[i + 1]
            i += 2
        elif arg == "--loop":
            loop = True
            i += 1
        elif arg == "--magazine":
            if i + 1 >= len(sys.argv):
                print("Error: --magazine requires an argument", file=sys.stderr)
                sys.exit(1)
            try:
                filter_magazine = int(sys.argv[i + 1])
                if filter_magazine < 1 or filter_magazine > 8:
                    print("Error: Magazine number must be between 1 and 8", file=sys.stderr)
                    sys.exit(1)
            except ValueError:
                print("Error: --magazine argument must be an integer", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif arg == "--page":
            if i + 1 >= len(sys.argv):
                print("Error: --page requires an argument", file=sys.stderr)
                sys.exit(1)
            filter_page = sys.argv[i + 1]
            i += 2
        else:
            print(f"Error: Unknown argument '{arg}'", file=sys.stderr)
            sys.exit(1)

    if not os.path.isfile(input_file):
        print(f"Error: File '{input_file}' not found", file=sys.stderr)
        sys.exit(1)

    try:
        restream(input_file, mask, time_format, loop,
                 filter_magazine=filter_magazine, filter_page=filter_page)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C when --loop is used


if __name__ == "__main__":
    main()

# Made with Bob

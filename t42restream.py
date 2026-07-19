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
    --control NAME=VAL  Force a page-header control bit on or off.
                        May be supplied multiple times. NAME may be C4-C11 or:
                        erase, newsflash, subtitle, suppress-header, update,
                        interrupted-sequence, inhibit-display, magazine-serial.
                        VAL may be 0/off/false or 1/on/true.
    --loop              Loop through the file indefinitely (streams continuously).
    --suppress-packet N Suppress all packets with packet number N (0-31).
                        May be supplied multiple times.
    --magazine MAG      Only stream packets from this magazine number (1-8).
    --page PAGE         Only stream packets for this page number (e.g. 172, 1BA).
                        Implies --magazine is set to the magazine of that page if
                        --magazine is not supplied explicitly.
    --interleave        Re-order the output stream so that pages from different
                        magazines are interleaved round-robin rather than output
                        in the order they appear in the file.  Each complete page
                        (header packet + all following row packets up to the next
                        header) is treated as one unit.  Compatible with --loop;
                        incompatible with --magazine / --page filters (those
                        options are ignored when --interleave is set).
    --magazine-parallel Re-order emitted packets so each magazine always maps to
                        stable VBI lines, with bandwidth proportional to the
                        number of pages in that magazine.  Low-traffic magazines
                        may share a VBI line, taking turns on it.  Compatible
                        with --loop; incompatible with --interleave.
    --vbi-lines N       Total number of VBI lines available when using
                        --magazine-parallel.  Default: 8.
"""

import sys
import os
import datetime

from teletext_helpers import hamming_8_4_decode, hamming_8_4_encode, encode_text_byte

PACKET_SIZE = 42
# Header text occupies packet bytes 10-41 (32 characters shown on screen)
HEADER_TEXT_START = 10
HEADER_TEXT_LEN = 32

DEFAULT_MASK = "?" * 24 + "########"
DEFAULT_TIME_FORMAT = "%H:%M:%S"

CONTROL_BIT_FIELDS = {
    'C4': (5, 3),
    'C5': (7, 2),
    'C6': (7, 3),
    'C7': (8, 0),
    'C8': (8, 1),
    'C9': (8, 2),
    'C10': (8, 3),
    'C11': (9, 0),
}

CONTROL_BIT_ALIASES = {
    'erase': 'C4',
    'newsflash': 'C5',
    'subtitle': 'C6',
    'suppress-header': 'C7',
    'suppress_header': 'C7',
    'update': 'C8',
    'interrupted-sequence': 'C9',
    'interrupted_sequence': 'C9',
    'inhibit-display': 'C10',
    'inhibit_display': 'C10',
    'magazine-serial': 'C11',
    'magazine_serial': 'C11',
}


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


def _parse_page_sort_key(header_packet):
    """
    Return a sort key (page_tens, page_units, subcode) for a header packet,
    used to order pages within a magazine by page number then sub-page.

    Sub-code is assembled from bytes 4-9 per ETS 300 706 §9.3.1.2:
      byte 4  → S1 (bits 0-3)
      byte 5  → S2 (bits 0-2) + C4 (bit 3, ignored)
      byte 6  → S3 (bits 0-3)
      byte 7  → S4 (bits 0-1) + C5-C6 (bits 2-3, ignored)

    Returns (page_tens, page_units, subcode); undecodable fields are
    replaced with 0 so the page still sorts stably.
    """
    page_units = hamming_8_4_decode(header_packet[2]) or 0
    page_tens  = hamming_8_4_decode(header_packet[3]) or 0
    s1 = hamming_8_4_decode(header_packet[4]) or 0
    s2 = hamming_8_4_decode(header_packet[5]) or 0
    s3 = hamming_8_4_decode(header_packet[6]) or 0
    s4 = hamming_8_4_decode(header_packet[7]) or 0
    subcode = (
        (s1 & 0x0F) |
        ((s2 & 0x07) << 4) |
        ((s3 & 0x0F) << 7) |
        ((s4 & 0x03) << 11)
    )
    return (page_tens, page_units, subcode)


def _apply_control_bit_overrides(packet_data, control_overrides):
    """
    Return a modified copy of *packet_data* with selected page-header control
    bits forced to the requested values.
    """
    if not control_overrides:
        return packet_data

    packet = bytearray(packet_data)
    decoded_bytes = {}

    for control_name, value in control_overrides.items():
        byte_index, bit_index = CONTROL_BIT_FIELDS[control_name]
        if byte_index not in decoded_bytes:
            decoded = hamming_8_4_decode(packet[byte_index])
            if decoded is None:
                raise ValueError(
                    f"Cannot decode header control byte {byte_index} to override {control_name}."
                )
            decoded_bytes[byte_index] = decoded

        nibble = decoded_bytes[byte_index]
        if value:
            nibble |= (1 << bit_index)
        else:
            nibble &= ~(1 << bit_index)
        decoded_bytes[byte_index] = nibble

    for byte_index, nibble in decoded_bytes.items():
        packet[byte_index] = hamming_8_4_encode(nibble)

    return bytes(packet)



def _apply_time_to_header(packet_data, mask, time_format, control_overrides=None):
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
        control_overrides: optional dict mapping control names (C4-C11) to 0/1

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

    packet = bytearray(_apply_control_bit_overrides(packet_data, control_overrides))
    time_index = 0
    for i, ch in enumerate(mask):
        if ch == '#':
            byte_pos = HEADER_TEXT_START + i
            packet[byte_pos] = encode_text_byte(time_str[time_index])
            time_index += 1

    return bytes(packet)


def _read_pages_by_magazine(input_file):
    """
    Scan *input_file* and return a dict mapping magazine number (1-8) to a
    list of pages, where each page is a list of raw 42-byte packet bytestrings.

    A page starts with a packet_number==0 (header) packet and ends just before
    the next header packet for the same magazine, or at EOF.  Packets whose
    address cannot be decoded are discarded.
    """
    pages_by_mag = {}  # mag -> list of pages; each page is list[bytes]

    # current_page[mag] holds the packets accumulated for the in-progress page
    current_page = {}

    with open(input_file, 'rb') as f:
        while True:
            packet = f.read(PACKET_SIZE)
            if len(packet) < PACKET_SIZE:
                break

            magazine, packet_number = _parse_packet_address(packet)
            if magazine is None:
                continue

            if packet_number == 0:
                # Flush any in-progress page for this magazine
                if magazine in current_page and current_page[magazine]:
                    pages_by_mag.setdefault(magazine, []).append(current_page[magazine])
                current_page[magazine] = [packet]
            else:
                if magazine in current_page:
                    current_page[magazine].append(packet)
                # Packets arriving before the first header for a magazine are dropped

    # Flush remaining in-progress pages at EOF
    for mag, page in current_page.items():
        if page:
            pages_by_mag.setdefault(mag, []).append(page)

    # Sort pages within each magazine by page number.  Pages with the same base
    # page number (tens, units) preserve their original file order relative to
    # each other (stable sort), so duplicate sub-page sequences stay intact.
    for mag in pages_by_mag:
        pages_by_mag[mag].sort(key=lambda page: _parse_page_sort_key(page[0])[:2])

    return pages_by_mag


def _interleave_pages(pages_by_mag):
    """
    Given a dict of {magazine: [page, ...]}, yield pages interleaved so that
    sub-pages are stepped through one at a time, with magazines interleaved
    round-robin on every step.

    For example, with pages 100 (3 sub-pages), 200 (2 sub-pages), 300 (1
    sub-page) the output order is:
        100/0001, 200/0001, 300/0001,
        100/0002, 200/0002, 300/0001,   ← 300 wraps back to its only sub-page
        100/0003, 200/0001, 300/0001    ← 200 wraps back too

    Pages within each magazine are grouped by base page number (tens, units).
    All base-page slots across all magazines are collected into a flat ordered
    list; on each sub-page step every slot yields sub-page index N % len(slot).
    The outer loop runs max_subpages times (the maximum sub-page count of any
    single base page).

    Each yielded value is a list[bytes] representing one complete page.
    """
    magazines = sorted(pages_by_mag.keys())

    # Group each magazine's pages into per-base-page sub-page lists.
    # slots_by_mag[mag] = [ [100/0001, 100/0002], [101/0001], ... ]
    slots_by_mag = {}
    for mag in magazines:
        seen = {}       # (tens, units) -> index in this magazine's slot list
        mag_slots = []
        for page in pages_by_mag[mag]:
            key = _parse_page_sort_key(page[0])[:2]  # (tens, units)
            if key not in seen:
                seen[key] = len(mag_slots)
                mag_slots.append([])
            mag_slots[seen[key]].append(page)
        slots_by_mag[mag] = mag_slots

    # Interleave slot lists across magazines: take slot 0 from each mag, then
    # slot 1 from each mag, etc.  This gives the desired order:
    #   mag1/page0, mag2/page0, mag3/page0,
    #   mag1/page1, mag2/page1, mag3/page1, ...
    max_pages_per_mag = max(len(slots_by_mag[mag]) for mag in magazines)
    slots = []
    for page_idx in range(max_pages_per_mag):
        for mag in magazines:
            mag_slots = slots_by_mag[mag]
            if page_idx < len(mag_slots):
                slots.append(mag_slots[page_idx])

    max_subpages = max(len(slot) for slot in slots)

    for subpage_idx in range(max_subpages):
        for slot in slots:
            yield slot[subpage_idx % len(slot)]


def _group_pages_into_slots(pages):
    """Group sorted pages into per-base-page sub-page slots."""
    seen = {}
    slots = []

    for page in pages:
        key = _parse_page_sort_key(page[0])[:2]
        if key not in seen:
            seen[key] = len(slots)
            slots.append([])
        slots[seen[key]].append(page)

    return slots



def restream(input_file, mask, time_format, loop, output=None,
             filter_magazine=None, filter_page=None, interleave=False,
             magazine_parallel=False, vbi_lines=8, control_overrides=None,
             suppressed_packet_numbers=None):
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
        interleave: if True, re-order the stream so pages from different
                    magazines are interleaved round-robin
        magazine_parallel: if True, emit packets with bandwidth proportional to
                           each magazine's page count, pinned to stable VBI lines.
                           Low-traffic magazines may share a line.
        vbi_lines: total VBI lines to distribute across magazines (default 8)
        control_overrides: optional dict mapping control names (C4-C11) to 0/1
        suppressed_packet_numbers: optional set of packet numbers (0-31) to drop
    """
    if len(mask) != HEADER_TEXT_LEN:
        raise ValueError(
            f"Mask must be exactly {HEADER_TEXT_LEN} characters long (got {len(mask)})."
        )

    if output is None:
        output = sys.stdout.buffer

    if interleave and magazine_parallel:
        raise ValueError("--interleave and --magazine-parallel cannot be used together")

    if interleave:
        _restream_interleaved(input_file, mask, time_format, loop, output,
                              control_overrides, suppressed_packet_numbers)
        return

    if magazine_parallel:
        _restream_magazine_lines(input_file, mask, time_format, loop, output,
                                 vbi_lines, control_overrides, suppressed_packet_numbers)
        return

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

            if suppressed_packet_numbers and packet_number in suppressed_packet_numbers:
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
                    packet = _apply_time_to_header(packet, mask, time_format,
                                                   control_overrides)
                else:
                    #ensure we don't output non matching header packets
                    continue
            else:
                # Non-header packet — emit only if we are inside a matching page
                if not current_page_matches:
                    continue

            output.write(packet)
            output.flush()


def _restream_interleaved(input_file, mask, time_format, loop, output,
                         control_overrides=None, suppressed_packet_numbers=None):
    """
    Emit packets from *input_file* interleaved round-robin by magazine.

    On each pass through the file all pages are bucketed by magazine; pages
    are then emitted one-at-a-time cycling through magazines in sorted order.
    When *loop* is True this repeats indefinitely.
    """
    while True:
        pages_by_mag = _read_pages_by_magazine(input_file)
        if not pages_by_mag:
            if not loop:
                break
            continue

        for page_packets in _interleave_pages(pages_by_mag):
            header_packet = page_packets[0]
            _, header_packet_number = _parse_packet_address(header_packet)
            if not (suppressed_packet_numbers and header_packet_number in suppressed_packet_numbers):
                header = _apply_time_to_header(header_packet, mask, time_format,
                                               control_overrides)
                output.write(header)
                output.flush()
            for pkt in page_packets[1:]:
                _, packet_number = _parse_packet_address(pkt)
                if suppressed_packet_numbers and packet_number in suppressed_packet_numbers:
                    continue
                output.write(pkt)
                output.flush()

        if not loop:
            break


def _build_vbi_schedule(page_counts_by_mag, vbi_lines):
    """
    Return a list of length *vbi_lines* where each element is a list of
    magazine numbers assigned to that VBI line slot.

    Bandwidth is proportional to page count.  The schedule is built using
    the Bresenham / largest-remainder method so each magazine appears in
    exactly round(share) slots; magazines whose share is less than 0.5 share
    a slot with other low-traffic magazines via round-robin.

    The returned slot list is stable: re-calling with the same inputs always
    produces the same assignment.
    """
    magazines = sorted(page_counts_by_mag)
    total_pages = sum(page_counts_by_mag.values())

    if total_pages == 0 or not magazines:
        return [[] for _ in range(vbi_lines)]

    # Compute exact floating share and round to nearest integer (>= 0).
    exact = {mag: page_counts_by_mag[mag] / total_pages * vbi_lines
             for mag in magazines}
    floored = {mag: int(exact[mag]) for mag in magazines}
    remainders = sorted(magazines,
                        key=lambda m: exact[m] - floored[m],
                        reverse=True)
    allocated = dict(floored)
    deficit = vbi_lines - sum(allocated.values())
    for mag in remainders[:deficit]:
        allocated[mag] += 1

    # Build the slot list: magazines with >= 1 whole slot get that many
    # consecutive slots.  Magazines with 0 slots are queued to share slots.
    slots = []
    sharing_queue = []   # magazines that got 0 whole slots
    for mag in magazines:
        n = allocated[mag]
        if n >= 1:
            for _ in range(n):
                slots.append([mag])
        else:
            sharing_queue.append(mag)

    # Distribute shared magazines into existing slots, preferring the highest-
    # indexed slot with the fewest tenants so that the primary (lowest) line for
    # each magazine stays unshared where possible.
    for mag in sharing_queue:
        # Reverse the index range so that ties resolve to the highest slot.
        target = min(reversed(range(len(slots))), key=lambda i: len(slots[i]))
        slots[target].append(mag)

    # Pad to vbi_lines if rounding left us short (shouldn't happen, but be safe)
    while len(slots) < vbi_lines:
        slots.append([])

    return slots


def _make_filler_packet(magazine):
    """Return a blank packet 25 (filler) for *magazine*."""
    raw = (25 << 3) | (magazine & 0x07)
    return bytes([
        hamming_8_4_encode(raw & 0x0F),
        hamming_8_4_encode((raw >> 4) & 0x0F),
        *([encode_text_byte(' ')] * (PACKET_SIZE - 2)),
    ])


def _emit_one_packet(magazine, state_by_mag, slots_by_mag, active_magazines,
                     mask, time_format, control_overrides,
                     suppressed_packet_numbers, loop, max_cycles,
                     cycle_count_by_mag, filler_packets, primary_line,
                     current_line_idx, header_emitted_this_field, output):
    """
    Emit the next packet for *magazine* and advance its state.

    If the next packet to emit is a page header (packet_number == 0) and
    *current_line_idx* is not this magazine's primary line, a filler packet is
    emitted instead and the state is left unchanged so the header is deferred
    to the next turn when the primary line is active.

    If a header was already emitted for *magazine* earlier in the current field
    (tracked via *header_emitted_this_field*), a filler is emitted and state is
    left unchanged so that content packets don't appear in the same field as
    their header.

    Removes the magazine from *active_magazines* when its run is complete
    (only relevant when loop=False).
    """
    if magazine not in active_magazines:
        return

    slots = slots_by_mag[magazine]
    state = state_by_mag[magazine]
    slot = slots[state['slot']]
    page_packets = slot[state['subpage'] % len(slot)]
    packet = page_packets[state['packet']]
    _, packet_number = _parse_packet_address(packet)

    # If this is a header packet and we are not on the magazine's primary line,
    # emit a filler instead and leave state unchanged.
    if packet_number == 0 and current_line_idx != primary_line[magazine]:
        output.write(filler_packets[magazine])
        output.flush()
        return

    # If the header for the current page (identified by slot+subpage) was already
    # emitted in this field, hold off on its content packets until the next field.
    page_key = (magazine, state['slot'], state['subpage'] % len(slot))
    if packet_number != 0 and page_key in header_emitted_this_field:
        output.write(filler_packets[magazine])
        output.flush()
        return

    if not (suppressed_packet_numbers and packet_number in suppressed_packet_numbers):
        if packet_number == 0:
            packet = _apply_time_to_header(packet, mask, time_format,
                                           control_overrides)
            header_emitted_this_field.add(page_key)
        output.write(packet)
        output.flush()

    state['packet'] += 1
    if state['packet'] < len(page_packets):
        return

    state['packet'] = 0
    state['slot'] += 1
    if state['slot'] < len(slots):
        return

    state['slot'] = 0
    state['subpage'] += 1

    wrapped = all(state['subpage'] >= len(slot) for slot in slots)
    if wrapped:
        state['subpage'] = 0
        cycle_count_by_mag[magazine] += 1
        if not loop and cycle_count_by_mag[magazine] >= max_cycles:
            active_magazines.discard(magazine)


def _restream_magazine_lines(input_file, mask, time_format, loop, output,
                             vbi_lines=8, control_overrides=None,
                             suppressed_packet_numbers=None):
    """
    Emit packets proportionally by magazine page count, pinned to stable VBI
    lines.  Header packets are always emitted on the magazine's lowest (primary)
    VBI line; filler packets are used on other lines when a header is pending.
    """
    while True:
        pages_by_mag = _read_pages_by_magazine(input_file)
        if not pages_by_mag:
            if not loop:
                break
            continue

        page_counts = {mag: len(pages) for mag, pages in pages_by_mag.items()}
        vbi_schedule = _build_vbi_schedule(page_counts, vbi_lines)

        # Lowest line index assigned to each magazine — headers go here only
        primary_line = {}
        for line_idx, line_mags in enumerate(vbi_schedule):
            for mag in line_mags:
                if mag not in primary_line:
                    primary_line[mag] = line_idx

        filler_packets = {mag: _make_filler_packet(mag) for mag in pages_by_mag}

        slots_by_mag = {
            mag: _group_pages_into_slots(pages_by_mag[mag])
            for mag in pages_by_mag
        }
        state_by_mag = {mag: {'slot': 0, 'subpage': 0, 'packet': 0}
                        for mag in slots_by_mag}
        cycle_count_by_mag = {mag: 0 for mag in slots_by_mag}
        max_cycles = max(max(len(slot) for slot in slots)
                         for slots in slots_by_mag.values())

        # Per-VBI-line round-robin index for shared slots
        slot_turn = [0] * vbi_lines

        active_magazines = set(slots_by_mag)
        while active_magazines:
            header_emitted_this_field = set()
            for line_idx, line_mags in enumerate(vbi_schedule):
                if not line_mags:
                    continue
                # Pick which magazine takes this line this frame
                turn = slot_turn[line_idx] % len(line_mags)
                mag = line_mags[turn]
                slot_turn[line_idx] += 1

                if mag not in active_magazines:
                    continue

                _emit_one_packet(mag, state_by_mag, slots_by_mag,
                                 active_magazines, mask, time_format,
                                 control_overrides, suppressed_packet_numbers,
                                 loop, max_cycles, cycle_count_by_mag,
                                 filler_packets, primary_line, line_idx,
                                 header_emitted_this_field, output)

        if not loop:
            break



def _parse_control_override(spec):
    """Parse NAME=VALUE for --control and return (control_name, bit_value)."""
    if '=' not in spec:
        raise ValueError("Control override must be in the form NAME=VALUE")

    name, value_text = spec.split('=', 1)
    key = name.strip().lower()
    control_name = CONTROL_BIT_ALIASES.get(key, name.strip().upper())
    if control_name not in CONTROL_BIT_FIELDS:
        raise ValueError(f"Unknown control bit '{name}'")

    value_key = value_text.strip().lower()
    if value_key in ('1', 'on', 'true'):
        return control_name, 1
    if value_key in ('0', 'off', 'false'):
        return control_name, 0
    raise ValueError(f"Invalid control bit value '{value_text}'")



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
    interleave = False
    magazine_parallel = False
    vbi_lines = 8
    control_overrides = {}
    suppressed_packet_numbers = set()

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
        elif arg == "--interleave":
            interleave = True
            i += 1
        elif arg == "--magazine-parallel":
            magazine_parallel = True
            i += 1
        elif arg == "--vbi-lines":
            if i + 1 >= len(sys.argv):
                print("Error: --vbi-lines requires an argument", file=sys.stderr)
                sys.exit(1)
            try:
                vbi_lines = int(sys.argv[i + 1])
                if vbi_lines < 1:
                    print("Error: --vbi-lines must be at least 1", file=sys.stderr)
                    sys.exit(1)
            except ValueError:
                print("Error: --vbi-lines argument must be an integer", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif arg == "--suppress-packet":
            if i + 1 >= len(sys.argv):
                print("Error: --suppress-packet requires an argument", file=sys.stderr)
                sys.exit(1)
            try:
                packet_number = int(sys.argv[i + 1])
            except ValueError:
                print("Error: --suppress-packet argument must be an integer", file=sys.stderr)
                sys.exit(1)
            if packet_number < 0 or packet_number > 31:
                print("Error: Packet number must be between 0 and 31", file=sys.stderr)
                sys.exit(1)
            suppressed_packet_numbers.add(packet_number)
            i += 2
        elif arg == "--control":
            if i + 1 >= len(sys.argv):
                print("Error: --control requires an argument", file=sys.stderr)
                sys.exit(1)
            try:
                control_name, control_value = _parse_control_override(sys.argv[i + 1])
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            control_overrides[control_name] = control_value
            i += 2
        else:
            print(f"Error: Unknown argument '{arg}'", file=sys.stderr)
            sys.exit(1)

    if not os.path.isfile(input_file):
        print(f"Error: File '{input_file}' not found", file=sys.stderr)
        sys.exit(1)

    try:
        restream(input_file, mask, time_format, loop,
                 filter_magazine=filter_magazine, filter_page=filter_page,
                 interleave=interleave, magazine_parallel=magazine_parallel,
                 vbi_lines=vbi_lines, control_overrides=control_overrides,
                 suppressed_packet_numbers=suppressed_packet_numbers)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C when --loop is used


if __name__ == "__main__":
    main()

# Made with Bob

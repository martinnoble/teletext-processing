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
    --interleave        Re-order the output stream so that pages from different
                        magazines are interleaved round-robin rather than output
                        in the order they appear in the file.  Each complete page
                        (header packet + all following row packets up to the next
                        header) is treated as one unit.  Compatible with --loop
                        and --vbi-lines.
    --magazine-parallel Re-order emitted packets so bandwidth across available
                        VBI lines is proportional to each magazine's page count.
                        Lines are not locked to magazines; any line may carry any
                        magazine's packet.  If a header for a magazine is emitted
                        in a field, no further packets for that magazine follow in
                        the same field — other magazines fill those remaining
                        slots instead, or a filler packet is used when no other
                        magazine has a packet available.
                        Compatible with --loop; incompatible with --interleave.
    --vbi-lines N       Total number of VBI lines available.  Used by both
                        --magazine-parallel and --interleave.  Default: 8.
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
             interleave=False, magazine_parallel=False, vbi_lines=8,
             control_overrides=None):
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
        interleave: if True, re-order the stream so pages from different
                    magazines are interleaved round-robin
        magazine_parallel: if True, emit packets with bandwidth proportional to
                           each magazine's page count, pinned to stable VBI lines.
                           Low-traffic magazines may share a line.
        vbi_lines: total VBI lines to distribute across magazines (default 8)
        control_overrides: optional dict mapping control names (C4-C11) to 0/1
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
                              vbi_lines, control_overrides)
        return

    if magazine_parallel:
        _restream_magazine_parallel(input_file, mask, time_format, loop, output,
                                    vbi_lines, control_overrides)
        return

    with open(input_file, 'rb') as f:
        while True:
            packet = f.read(PACKET_SIZE)

            if len(packet) == 0:
                if loop:
                    f.seek(0)
                    continue
                break

            if len(packet) < PACKET_SIZE:
                # Incomplete trailing packet — skip and optionally loop
                if loop:
                    f.seek(0)
                    continue
                break

            magazine, packet_number = _parse_packet_address(packet)

            if magazine is None:
                output.write(packet)
                output.flush()
                continue

            if packet_number == 0:
                packet = _apply_time_to_header(packet, mask, time_format,
                                               control_overrides)

            output.write(packet)
            output.flush()


def _restream_interleaved(input_file, mask, time_format, loop, output,
                          vbi_lines=8, control_overrides=None):
    """
    Emit packets from *input_file* interleaved round-robin by magazine.

    On each pass through the file all pages are bucketed by magazine; pages
    are then emitted one-at-a-time cycling through magazines in sorted order.
    When *loop* is True this repeats indefinitely.

    A VBI "field" is *vbi_lines* packets wide.  The header packet of each page
    is emitted at the start of a fresh field.  Any remaining capacity in that
    field is padded with filler packets so that content packets of the same page
    never share a field with their own header.
    """
    while True:
        pages_by_mag = _read_pages_by_magazine(input_file)
        if not pages_by_mag:
            if not loop:
                break
            continue

        # Build filler packets keyed by magazine number.
        filler_packets = {mag: _make_filler_packet(mag) for mag in pages_by_mag}

        # Track how many packets have been emitted into the current field so we
        # know when we cross a field boundary.
        packets_in_field = 0

        for page_packets in _interleave_pages(pages_by_mag):
            magazine, _ = _parse_packet_address(page_packets[0])

            # Pad to the next field boundary before the header so the header
            # always lands at position 0 within a field.
            if packets_in_field > 0:
                padding = vbi_lines - packets_in_field
                filler = filler_packets.get(magazine, filler_packets[next(iter(filler_packets))])
                for _ in range(padding):
                    output.write(filler)
                    output.flush()
                packets_in_field = 0

            # Emit the header (position 0 of this field).
            header = _apply_time_to_header(page_packets[0], mask, time_format,
                                           control_overrides)
            output.write(header)
            output.flush()
            packets_in_field = 1

            # If there are content packets, pad the rest of this field with
            # fillers so content starts in the next field.
            if len(page_packets) > 1:
                padding = vbi_lines - packets_in_field
                filler = filler_packets.get(magazine, filler_packets[next(iter(filler_packets))])
                for _ in range(padding):
                    output.write(filler)
                    output.flush()
                packets_in_field = 0

                # Emit content packets, advancing the field counter.
                for pkt in page_packets[1:]:
                    output.write(pkt)
                    output.flush()
                    packets_in_field += 1
                    if packets_in_field >= vbi_lines:
                        packets_in_field = 0

        if not loop:
            break


def _credit_weights(page_counts_by_mag):
    """
    Return a dict mapping magazine → fractional credit earned per VBI slot.

    Each slot the magazine earns page_count/total_pages credits.  Over time
    a magazine that earns W credits per slot will be served W * vbi_lines
    packets per field on average — exactly proportional to its page count.
    """
    total = sum(page_counts_by_mag.values())
    if total == 0:
        return {mag: 0.0 for mag in page_counts_by_mag}
    return {mag: count / total for mag, count in page_counts_by_mag.items()}


def _make_filler_packet(magazine):
    """Return a blank packet 25 (filler) for *magazine*."""
    raw = (25 << 3) | (magazine & 0x07)
    return bytes([
        hamming_8_4_encode(raw & 0x0F),
        hamming_8_4_encode((raw >> 4) & 0x0F),
        *([encode_text_byte(' ')] * (PACKET_SIZE - 2)),
    ])


def _next_packet_for_mag(mag, state_by_mag, slots_by_mag):
    """Return the (packet_bytes, packet_number) for *mag* without advancing state."""
    state = state_by_mag[mag]
    slots = slots_by_mag[mag]
    slot = slots[state['slot']]
    page_packets = slot[state['subpage'] % len(slot)]
    packet = page_packets[state['packet']]
    _, packet_number = _parse_packet_address(packet)
    return packet, packet_number


def _advance_mag_state(mag, state_by_mag, slots_by_mag,
                       active_magazines, cycle_count_by_mag, max_cycles, loop):
    """Advance the cursor for *mag* after one packet has been emitted."""
    state = state_by_mag[mag]
    slots = slots_by_mag[mag]
    slot = slots[state['slot']]
    page_packets = slot[state['subpage'] % len(slot)]

    state['packet'] += 1
    if state['packet'] < len(page_packets):
        return

    state['packet'] = 0
    state['slot'] += 1
    if state['slot'] < len(slots):
        return

    state['slot'] = 0
    state['subpage'] += 1

    if all(state['subpage'] >= len(s) for s in slots):
        state['subpage'] = 0
        cycle_count_by_mag[mag] += 1
        if not loop and cycle_count_by_mag[mag] >= max_cycles:
            active_magazines.discard(mag)


def _restream_magazine_parallel(input_file, mask, time_format, loop, output,
                                 vbi_lines=8, control_overrides=None):
    """
    Emit packets proportionally by magazine page count across available VBI
    lines using deficit round-robin (DRR) scheduling.

    Each slot, every active magazine earns page_count/total_pages credits.
    The magazine with the highest accumulated credit (that is not locked out)
    is served.  Any unspent credit carries forward into the next field, so
    proportions are exact over time even though a single field may be heavily
    skewed toward one magazine.

    Each field is exactly *vbi_lines* packets wide.  Filler is only emitted
    when every active magazine has already sent a header this field and is
    therefore locked out for its remaining slots.

    The rule enforced: once a header for magazine M is emitted in a field, no
    further packets for M appear in that same field.
    """
    while True:
        pages_by_mag = _read_pages_by_magazine(input_file)
        if not pages_by_mag:
            if not loop:
                break
            continue

        page_counts = {mag: len(pages) for mag, pages in pages_by_mag.items()}
        weights = _credit_weights(page_counts)
        all_mags = sorted(pages_by_mag)

        # Pre-build one filler per magazine for use when all mags are locked out
        filler_packets = {mag: _make_filler_packet(mag) for mag in pages_by_mag}
        default_filler = filler_packets[all_mags[0]]

        slots_by_mag = {
            mag: _group_pages_into_slots(pages_by_mag[mag])
            for mag in pages_by_mag
        }
        state_by_mag = {mag: {'slot': 0, 'subpage': 0, 'packet': 0}
                        for mag in slots_by_mag}
        cycle_count_by_mag = {mag: 0 for mag in slots_by_mag}
        max_cycles = max(max(len(slot) for slot in slots)
                         for slots in slots_by_mag.values())

        active_magazines = set(slots_by_mag)
        # Each magazine starts with its weight as initial credit so that all
        # magazines are eligible immediately on the first slot.
        credits = {mag: weights[mag] for mag in all_mags}

        while active_magazines:
            # Mags that have already emitted a header this field — locked out
            # for the remainder of the field.
            header_emitted = set()

            for _ in range(vbi_lines):
                # Accrue one slot's worth of credits for every active magazine.
                for mag in active_magazines:
                    credits[mag] += weights[mag]

                # Pick the active, unlocked magazine with the highest credit.
                chosen = None
                best = -1.0
                for mag in all_mags:
                    if mag not in active_magazines:
                        continue
                    if mag in header_emitted:
                        continue
                    if credits[mag] > best:
                        best = credits[mag]
                        chosen = mag

                if chosen is None:
                    # All active mags locked out this field — emit filler.
                    output.write(default_filler)
                    output.flush()
                    continue

                credits[chosen] -= 1.0

                packet, packet_number = _next_packet_for_mag(
                    chosen, state_by_mag, slots_by_mag)

                if packet_number == 0:
                    packet = _apply_time_to_header(packet, mask, time_format,
                                                   control_overrides)
                    header_emitted.add(chosen)

                output.write(packet)
                output.flush()
                _advance_mag_state(chosen, state_by_mag, slots_by_mag,
                                   active_magazines, cycle_count_by_mag,
                                   max_cycles, loop)

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
    interleave = False
    magazine_parallel = False
    vbi_lines = 8
    control_overrides = {}

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
                 interleave=interleave, magazine_parallel=magazine_parallel,
                 vbi_lines=vbi_lines, control_overrides=control_overrides)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C when --loop is used


if __name__ == "__main__":
    main()

# Made with Bob

#!/usr/bin/env python3
"""
T42 Teletext Packet Parser

Processes T42 Teletext packet streams from binary files.
Each packet is 42 bytes (45 bytes minus the first 3 bytes of clock run-in and framing).
"""

from teletext_helpers import hamming_8_4_decode, decode_text_bytes


def parse_packet_header(packet_data):
    """
    Parse the header of a T42 packet to extract magazine and packet numbers.
    
    Args:
        packet_data: bytes object containing the 42-byte packet
        
    Returns:
        tuple: (magazine_number, packet_number) or (None, None) if error
    """
    if len(packet_data) < 2:
        return None, None
    
    # First two bytes are Hamming 8/4 encoded
    byte1 = packet_data[0]
    byte2 = packet_data[1]
    
    # Decode the two bytes
    decoded1 = hamming_8_4_decode(byte1)
    decoded2 = hamming_8_4_decode(byte2)
    
    if decoded1 is None or decoded2 is None:
        return None, None
    
    # Combine the two 4-bit values into an 8-bit value
    # byte1 contains lower 4 bits, byte2 contains upper 4 bits
    combined = (decoded2 << 4) | decoded1
    
    # Extract magazine number (first 3 bits)
    magazine = combined & 0x07
    
    # Magazine 0 is actually magazine 8
    if magazine == 0:
        magazine = 8
    
    # Extract packet number (last 5 bits)
    packet_number = (combined >> 3) & 0x1F
    
    return magazine, packet_number


def decode_page_header(packet_data):
    """
    Decode a page header packet (packet 0) to extract the page number, sub-code, control bits, and header text.
    
    Args:
        packet_data: bytes object containing the 42-byte packet
        
    Returns:
        tuple: (page_units, page_tens, subcode, control_bits, header_text) or (None, None, None, None, None) if error
    """
    if len(packet_data) < 42:
        return None, None, None, None, None
    
    # Bytes 2 and 3 contain the page number (after the 2-byte packet address)
    # Byte 2: page units (Hamming 8/4 encoded)
    # Byte 3: page tens (Hamming 8/4 encoded)
    page_units = hamming_8_4_decode(packet_data[2])
    page_tens = hamming_8_4_decode(packet_data[3])
    
    if page_units is None or page_tens is None:
        return None, None, None, None, None
    
    # Bytes 4-9 contain the sub-code and control bits (6 bytes, each Hamming 8/4 encoded)
    # S1 (byte 4): bits 0-3 of sub-code
    # S2 (byte 5): bits 0-2 are sub-code bits 4-6, bit 3 is C4
    # S3 (byte 6): bits 0-3 are sub-code bits 7-10
    # S4 (byte 7): bits 0-1 are sub-code bits 11-12, bits 2-3 are C5-C6
    # C8 (byte 8): bits 0-3 are C7-C10
    # C9 (byte 9): bits 0-3 are C11-C14 
    s1 = hamming_8_4_decode(packet_data[4])
    s2 = hamming_8_4_decode(packet_data[5])
    s3 = hamming_8_4_decode(packet_data[6])
    s4 = hamming_8_4_decode(packet_data[7])
    c8 = hamming_8_4_decode(packet_data[8])
    c9 = hamming_8_4_decode(packet_data[9])
    
    if s1 is None or s2 is None or s3 is None or s4 is None or c8 is None or c9 is None:
        subcode = None
        control_bits = None
    else:
        # Extract sub-code bits (13 bits total)
        # S1: bits 0-3 (sub-code bits 0-3)
        # S2: bits 0-2 (sub-code bits 4-6)
        # S3: bits 0-3 (sub-code bits 7-10)
        # S4: bits 0-1 (sub-code bits 11-12)
        subcode_bits = (
            (s1 & 0x0F) |           # bits 0-3
            ((s2 & 0x07) << 4) |    # bits 4-6
            ((s3 & 0x0F) << 7) |    # bits 7-10
            ((s4 & 0x03) << 11)     # bits 11-12
        )
        subcode = subcode_bits
        
        # Extract control bits (C4-C11, ignore C12-C14)
        # Based on byte descriptions:
        # S2 bit 3: C4
        # S4 bits 2-3: C5-C6
        # C8 bits 0-3: C7-C10
        # C9 bits 0: C11
        control_bits = {
            'Erase': (s2 >> 3) & 1,                    # C4 from S2 bit 3
            'Newsflash': (s4 >> 2) & 1,                # C5 from S4 bit 2
            'Subtitle': (s4 >> 3) & 1,                 # C6 from S4 bit 3
            'Suppress Header': (c8 >> 0) & 1,          # C7 from C8 bit 0
            'Update': (c8 >> 1) & 1,                   # C8 from C8 bit 1
            'Interrupted Sequence': (c8 >> 2) & 1,     # C9 from C8 bit 2
            'Inhibit Display': (c8 >> 3) & 1,          # C10 from C8 bit 3
            'Magazine Serial': (c9 >> 0) & 1,          # C11 from C9 bit 0
        }
    
    # The last 32 bytes (bytes 10-41) contain the header text
    header_text = decode_text_bytes(packet_data, 10, 42)
    
    return page_units, page_tens, subcode, control_bits, header_text


def decode_packet_27(packet_data, magazine):
    """
    Decode a Packet X/27/0-3 (editorial page linking) per ETS 300 706 §9.6.1.

    T42 byte indices (0-41 in a 42-byte packet) map to spec bytes as:
      index = spec_byte - 4   (spec bytes 4-5 are the 2-byte packet address at indices 0-1)

    Structure:
      Index 2  (spec byte 6)  : Designation code, Hamming 8/4 coded (0-3 editorial, 4-7 compositional)
      Indices 3-38 (spec bytes 7-42): 6 link groups × 6 bytes, all Hamming 8/4 coded.
        Each group mirrors bytes 6-11 of a page header (§9.3.1):
          +0 : page units           (bits 0-3)
          +1 : page tens            (bits 0-3)
          +2 : sub-code S1          (bits 0-3)
          +3 : sub-code S2 + M1     (bits 0-2 = S2, bit 3 = M1)
          +4 : sub-code S3          (bits 0-3)
          +5 : sub-code S4 + M2,M3  (bits 0-1 = S4, bit 2 = M2, bit 3 = M3)
      Index 39 (spec byte 43) : Link Control Byte, Hamming 8/4 (X/27/0 only)
        bit 3 of decoded nibble = show row 24 flag
      Indices 40-41 (spec bytes 44-45): CRC, raw 8-bit data (X/27/0 only)
        byte 44 = CRC bits 9-16, byte 45 = CRC bits 1-8

    Args:
        packet_data: bytes — 42-byte T42 packet starting at the packet address bytes
        magazine: int — magazine number (1-8) from the packet address, used as the
                  base for the relative magazine XOR (M1/M2/M3 bits)

    Returns:
        dict with keys:
          'designation_code': int
          'links': list of 6 dicts, each with:
              'page'    : str  — full page identifier e.g. "172", or None if undecodable
              'subcode' : int  — 13-bit sub-code, or None
              'no_page' : bool — True when the address is XFF:3F7F (no page specified)
          'link_control' : int or None — decoded LC nibble (X/27/0 only)
          'show_row_24'  : bool or None — whether row 24 data should be displayed (X/27/0 only)
          'crc'          : int or None  — 16-bit page CRC (X/27/0 only)
    """
    if len(packet_data) < 42:
        return None

    # Index 2 = spec byte 6 = designation code
    desig_raw = hamming_8_4_decode(packet_data[2])
    if desig_raw is None:
        return None
    designation_code = desig_raw & 0x0F

    links = []
    # Six link groups, each 6 bytes, starting at index 3 (spec byte 7)
    for n in range(6):
        base = 3 + n * 6

        pu_raw = hamming_8_4_decode(packet_data[base + 0])  # page units
        pt_raw = hamming_8_4_decode(packet_data[base + 1])  # page tens
        s1_raw = hamming_8_4_decode(packet_data[base + 2])  # S1
        s2_raw = hamming_8_4_decode(packet_data[base + 3])  # S2 + M1
        s3_raw = hamming_8_4_decode(packet_data[base + 4])  # S3
        s4_raw = hamming_8_4_decode(packet_data[base + 5])  # S4 + M2 + M3

        if any(v is None for v in (pu_raw, pt_raw, s1_raw, s2_raw, s3_raw, s4_raw)):
            links.append({'page': None, 'subcode': None, 'no_page': False})
            continue

        page_units = pu_raw & 0x0F
        page_tens  = pt_raw & 0x0F

        # M1/M2/M3 XOR the packet's own magazine number to derive the link's magazine
        m1 = (s2_raw >> 3) & 1   # bit 3 of the S2 byte (same position as C4 in page header)
        m2 = (s4_raw >> 2) & 1   # bit 2 of the S4 byte (same position as C5 in page header)
        m3 = (s4_raw >> 3) & 1   # bit 3 of the S4 byte (same position as C6 in page header)
        link_mag = magazine ^ (m1 | (m2 << 1) | (m3 << 2))
        if link_mag == 0:
            link_mag = 8

        # Assemble 13-bit sub-code: S1 (bits 0-3), S2 (bits 4-6), S3 (bits 7-10), S4 (bits 11-12)
        s1 = s1_raw & 0x0F
        s2 = s2_raw & 0x07
        s3 = s3_raw & 0x0F
        s4 = s4_raw & 0x03
        subcode = s1 | (s2 << 4) | (s3 << 7) | (s4 << 11)

        # Address XFF:3F7F means "no page specified"
        no_page = (page_units == 0xF and page_tens == 0xF and subcode == 0x1F7F)

        links.append({
            'page': f"{link_mag:X}{page_tens:X}{page_units:X}",
            'subcode': subcode,
            'no_page': no_page,
        })

    # Bytes 43-45 (indices 39-41) are only defined for X/27/0
    link_control = None
    show_row_24 = None
    crc = None

    if designation_code == 0:
        # Index 39 = spec byte 43 = Link Control Byte (Hamming 8/4)
        lc_raw = hamming_8_4_decode(packet_data[39])
        if lc_raw is not None:
            link_control = lc_raw & 0x0F
            show_row_24 = bool((link_control >> 3) & 1)
        # Indices 40-41 = spec bytes 44-45 = CRC (raw 8-bit, not Hamming coded)
        # Spec: byte 44 = CRC bits 9-16, byte 45 = CRC bits 1-8
        crc = (packet_data[40] << 8) | packet_data[41]

    return {
        'designation_code': designation_code,
        'links': links,
        'link_control': link_control,
        'show_row_24': show_row_24,
        'crc': crc,
    }


def decode_data_packet(packet_data):
    """
    Decode a data packet (packets 1-24) to extract text content.
    
    Args:
        packet_data: bytes object containing the 42-byte packet
        
    Returns:
        str: decoded text from the packet (40 bytes)
    """
    if len(packet_data) < 42:
        return None
    
    # The last 40 bytes (bytes 2-41) contain the text data
    return decode_text_bytes(packet_data, 2, 42)


def analyze_page_statistics(filename, only_deviations=False):
    """
    Analyze packet counts for each page appearance and flag deviations.
    
    Args:
        filename: path to the binary file containing T42 packets
        only_deviations: if True, only show pages with deviations
    """
    packet_size = 42
    page_appearances = {}  # {page_hex: [(packet_count, packet_numbers_set)]}
    current_page = None
    current_page_packet_count = 0
    current_page_packets = set()  # Track which packet numbers are present
    total_packets = 0
    
    try:
        with open(filename, 'rb') as f:
            while True:
                packet = f.read(packet_size)
                
                if len(packet) == 0:
                    break
                
                if len(packet) < packet_size:
                    break
                
                total_packets += 1
                
                magazine, packet_number = parse_packet_header(packet)
                
                if magazine is not None and packet_number is not None:
                    if packet_number == 0:
                        # Header packet - new page
                        page_units, page_tens, subcode, control_bits, header_text = decode_page_header(packet)
                        
                        if page_units is not None and page_tens is not None:
                            # Save previous page stats
                            if current_page is not None:
                                if current_page not in page_appearances:
                                    page_appearances[current_page] = []
                                page_appearances[current_page].append((current_page_packet_count, current_page_packets.copy()))
                            
                            # Start new page
                            page_hex = f"{magazine:X}{page_tens:X}{page_units:X}"
                            current_page = page_hex
                            #print (f"Got header: {page_hex}\n")
                            current_page_packet_count = 1  # Count the header packet
                            current_page_packets = {0}  # Header is packet 0
                        else:
                            current_page = None
                            current_page_packet_count = 0
                            current_page_packets = set()
                    else:
                        # Data packet
                        if current_page is not None:
                            current_page_packet_count += 1
                            #print(f" - Packet: {packet_number}")
                            if packet_number in current_page_packets:
                                print(f" [Duplicate]")
                            current_page_packets.add(packet_number)
                            #print(f"\n")
            
            # Save last page stats
            if current_page is not None:
                if current_page not in page_appearances:
                    page_appearances[current_page] = []
                page_appearances[current_page].append((current_page_packet_count, current_page_packets.copy()))
        
        # Analyze and display statistics
        print(f"Total packets processed: {total_packets}\n")
        
        if only_deviations:
            print("Pages with Deviations:")
        else:
            print("Page Statistics:")
        print("=" * 80)
        
        pages_with_deviations = 0
        
        for page in sorted(page_appearances.keys()):
            appearances = page_appearances[page]
            if len(appearances) == 0:
                continue
            
            # Extract counts and packet sets
            counts = [count for count, _ in appearances]
            packet_sets = [packets for _, packets in appearances]
            
            avg = sum(counts) / len(counts)
            min_count = min(counts)
            max_count = max(counts)
            
            # Calculate standard deviation
            variance = sum((x - avg) ** 2 for x in counts) / len(counts)
            std_dev = variance ** 0.5
            
            # Find the most common set of packets (the "expected" set)
            # Use the appearance with count closest to average
            closest_to_avg_idx = min(range(len(counts)), key=lambda i: abs(counts[i] - avg))
            expected_packets = packet_sets[closest_to_avg_idx]
            
            # Flag deviations (more than 2 standard deviations from mean)
            threshold = 2.0
            deviations = []
            for i, (count, packets) in enumerate(appearances):
                if abs(count - avg) > threshold * std_dev:
                    deviation_pct = ((count - avg) / avg) * 100
                    # Find missing and extra packets
                    missing = expected_packets - packets
                    extra = packets - expected_packets
                    deviations.append((i + 1, count, deviation_pct, missing, extra))
            
            # Skip pages without deviations if only_deviations is True
            if only_deviations and not deviations:
                continue
            
            if deviations:
                pages_with_deviations += 1
            
            print(f"\nPage {page}:")
            print(f"  Appearances: {len(counts)}")
            print(f"  Average packets: {avg:.1f}")
            print(f"  Min: {min_count}, Max: {max_count}")
            print(f"  Std deviation: {std_dev:.2f}")
            print(f"  Expected packets: {sorted(expected_packets)}")
            
            if deviations:
                print(f"  ⚠ Deviations detected (>{threshold}σ):")
                for appearance, count, pct, missing, extra in deviations:
                    print(f"    Appearance #{appearance}: {count} packets ({pct:+.1f}%)")
                    if missing:
                        print(f"      Missing packets: {sorted(missing)}")
                    if extra:
                        print(f"      Extra packets: {sorted(extra)}")
        
        print("\n" + "=" * 80)
        if only_deviations:
            print(f"Pages with deviations: {pages_with_deviations}")
        else:
            print(f"Total pages: {len(page_appearances)}, Pages with deviations: {pages_with_deviations}")
        
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found")
    except Exception as e:
        print(f"Error processing file: {e}")


def process_t42_file(filename, filter_magazine=None, decode_data=False, filter_page=None):
    """
    Process a T42 binary file and extract packet information.
    
    Args:
        filename: path to the binary file containing T42 packets
        filter_magazine: if specified, only show packets from this magazine number
        decode_data: if True, decode and display text from data packets (1-24)
        filter_page: if specified, only show packets for this page number (e.g., "172")
    """
    packet_size = 42
    packet_count = 0
    filtered_count = 0
    current_page_matches = False  # Track if we're in a matching page
    page_appearance_counts = {}  # Track how many times each page has appeared
    
    try:
        with open(filename, 'rb') as f:
            while True:
                # Read one packet (42 bytes)
                packet = f.read(packet_size)
                
                if len(packet) == 0:
                    break  # End of file
                
                if len(packet) < packet_size:
                    print(f"Warning: Incomplete packet at end of file ({len(packet)} bytes)")
                    break
                
                packet_count += 1
                
                # Parse the packet header
                magazine, packet_number = parse_packet_header(packet)
                
                if magazine is not None and packet_number is not None:
                    # Check if this is a header packet (packet 0)
                    if packet_number == 0:
                        page_units, page_tens, subcode, control_bits, header_text = decode_page_header(packet)
                        if page_units is not None and page_tens is not None:
                            # Page number is in hex format
                            page_hex = f"{magazine:X}{page_tens:X}{page_units:X}"
                            
                            # Increment appearance counter for this page
                            if page_hex not in page_appearance_counts:
                                page_appearance_counts[page_hex] = 0
                            page_appearance_counts[page_hex] += 1
                            appearance_num = page_appearance_counts[page_hex]
                            
                            # Check if this page matches our filters
                            page_matches = True
                            if filter_magazine is not None and magazine != filter_magazine:
                                page_matches = False
                            if filter_page is not None and page_hex != filter_page.upper():
                                page_matches = False
                            
                            current_page_matches = page_matches
                            
                            if page_matches:
                                subcode_str = f".{subcode:04X}" if subcode is not None else ""
                                print(f"Packet {packet_count}: Magazine {magazine}, Packet {packet_number} (Header) - Page {page_hex}{subcode_str} [#{appearance_num}]")
                                if header_text:
                                    print(f"  Header: {header_text}")
                                if control_bits:
                                    # Display only active control bits (value = 1)
                                    active_controls = [name for name, value in control_bits.items() if value == 1]
                                    if active_controls:
                                        ctrl_str = ", ".join(active_controls)
                                        print(f"  Control: {ctrl_str}")
                                filtered_count += 1
                        else:
                            current_page_matches = False
                    else:
                        # Non-header packet - only show if we're in a matching page
                        if current_page_matches:
                            # Apply magazine filter if specified
                            if filter_magazine is None or magazine == filter_magazine:
                                if decode_data and 1 <= packet_number <= 24:
                                    # Decode data packet text - output with packet number prefix
                                    text = decode_data_packet(packet)
                                    if text:
                                        print(f"[{packet_number:02d}]: {text}")
                                elif packet_number == 27:
                                    # Editorial / compositional page linking packet
                                    p27 = decode_packet_27(packet, magazine)
                                    if p27 is not None:
                                        dc = p27['designation_code']
                                        print(f"Packet {packet_count}: Magazine {magazine}, Packet 27/{dc} (Page Links)")
                                        link_names = ["Red", "Green", "Yellow", "Cyan", "Index", "Next"]
                                        for i, link in enumerate(p27['links']):
                                            name = link_names[i] if i < len(link_names) else f"Link {i}"
                                            if link['page'] is None:
                                                print(f"  {name}: [decode error]")
                                            elif link['no_page']:
                                                print(f"  {name}: (none)")
                                            else:
                                                sc_str = f":{link['subcode']:04X}" if link['subcode'] is not None else ""
                                                print(f"  {name}: {link['page']}{sc_str}")
                                        if dc == 0:
                                            row24_str = "yes" if p27['show_row_24'] else "no"
                                            print(f"  Show row 24: {row24_str}")
                                            if p27['crc'] is not None:
                                                print(f"  CRC: 0x{p27['crc']:04X}")
                                    else:
                                        print(f"Packet {packet_count}: Magazine {magazine}, Packet {packet_number} (decode error)")
                                else:
                                    print(f"Packet {packet_count}: Magazine {magazine}, Packet {packet_number}")
                                filtered_count += 1
                else:
                    if filter_magazine is None:
                        print(f"Packet {packet_count}: Error decoding header")
        
        print(f"\nTotal packets processed: {packet_count}")
        if filter_magazine is not None:
            print(f"Magazine {filter_magazine} packets: {filtered_count}")
        
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found")
    except Exception as e:
        print(f"Error processing file: {e}")


def main():
    """Main entry point for the script."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python t42parser.py <input_file> [options]")
        print("\nProcesses a T42 Teletext packet stream from a binary file.")
        print("Each packet should be 42 bytes (45 bytes minus clock run-in and framing).")
        print("\nOptional arguments:")
        print("  --magazine MAG      Filter packets from specified magazine (1-8)")
        print("  --page PAGE         Filter to specific page number (e.g., 172, 1BA)")
        print("  --decode-data       Decode and display text from data packets (1-24)")
        print("  --stats             Analyze packet counts per page and flag deviations")
        print("  --deviations-only   With --stats, only show pages with deviations")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    # Check for options
    filter_magazine = None
    filter_page = None
    decode_data = False
    stats_mode = False
    only_deviations = False
    
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--decode-data":
            decode_data = True
            i += 1
        elif arg == "--stats":
            stats_mode = True
            i += 1
        elif arg == "--deviations-only":
            only_deviations = True
            i += 1
        elif arg == "--magazine":
            if i + 1 < len(sys.argv):
                try:
                    filter_magazine = int(sys.argv[i + 1])
                    if filter_magazine < 1 or filter_magazine > 8:
                        print("Error: Magazine number must be between 1 and 8")
                        sys.exit(1)
                    i += 2
                except ValueError:
                    print("Error: Magazine number must be an integer")
                    sys.exit(1)
            else:
                print("Error: --magazine requires a magazine number argument")
                sys.exit(1)
        elif arg == "--page":
            if i + 1 < len(sys.argv):
                filter_page = sys.argv[i + 1]
                i += 2
            else:
                print("Error: --page requires a page number argument")
                sys.exit(1)
        else:
            print(f"Error: Unknown argument '{arg}'")
            sys.exit(1)
    
    # Stats mode is exclusive
    if stats_mode:
        analyze_page_statistics(input_file, only_deviations)
    else:
        if only_deviations:
            print("Warning: --deviations-only only works with --stats mode")
            print()
        if filter_magazine:
            print(f"Filtering for Magazine {filter_magazine} packets only")
        if filter_page:
            print(f"Filtering for Page {filter_page.upper()}")
        if decode_data:
            print("Decoding data packets (1-24)")
        if filter_magazine or filter_page or decode_data:
            print()
        
        process_t42_file(input_file, filter_magazine, decode_data, filter_page)


if __name__ == "__main__":
    main()

# Made with Bob

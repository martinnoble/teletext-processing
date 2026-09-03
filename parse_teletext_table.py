#!/usr/bin/env python3
"""Parse the teletext table HTML from computer-legacy.com and produce a CSV."""

import re
import csv
import sys

html = sys.stdin.read()

def clean(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if text == '-':
        text = ''
    return text

def extract_href(cell, base='https://computer-legacy.com'):
    m = re.search(r'href="(/[^"]+)"', cell)
    return base + m.group(1) if m else ''

rows = re.findall(r'<tr>\s*(.*?)\s*</tr>', html, re.DOTALL)

out_rows = []

for row in rows:
    cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
    if len(cells) < 12:
        continue

    batch    = clean(cells[0])
    date     = clean(cells[1])
    year, month, day = ('', '', '')
    if date:
        date_parts = date.split('-')
        if len(date_parts) == 3:
            year, month, day = date_parts
    time_val = clean(cells[2]).strip(' -').strip()
    service  = clean(cells[3])
    channel  = clean(cells[4])

    # Programme: strip the genome anchor but capture its href
    prog_cell = cells[5]
    genome_url = ''
    gm = re.search(r'href="(https://genome[^"]+)"', prog_cell)
    if gm:
        genome_url = gm.group(1)
    prog_clean = re.sub(r'<a[^>]*>.*?</a>', '', prog_cell, flags=re.DOTALL)
    programme = clean(prog_clean)

    tape_type = clean(cells[6])

    # Rating cell
    rc = cells[7]
    stars = rc.count('⭐')
    first_for_date = 'Yes' if '1st FOR DATE' in rc else ''
    digitiser      = 'Yes' if 'DIGITISER' in rc else ''
    rating_raw = clean(rc)
    rating_notes = re.sub(r'[⭐🌟🎮]+', '', rating_raw)
    rating_notes = re.sub(r'(1st FOR DATE|DIGITISER RECOVERED)', '', rating_notes).strip()

    vcr = clean(cells[8])

    deconvolved_url = extract_href(cells[9])
    squashed_url    = extract_href(cells[10])
    final_url       = extract_href(cells[11])
    preview_url     = extract_href(cells[12]) if len(cells) > 12 else ''

    out_rows.append([
        batch, date, year, month, day, time_val, service, channel, programme,
        genome_url, tape_type, stars, first_for_date, digitiser,
        rating_notes, vcr, deconvolved_url, squashed_url, final_url, preview_url
    ])

writer = csv.writer(sys.stdout)
writer.writerow([
    'Batch', 'Date', 'Year', 'Month', 'Day', 'Time', 'Service', 'Channel', 'Programme',
    'Genome URL', 'Tape Type', 'Stars', 'First For Date', 'Digitiser Recovered',
    'Rating Notes', 'VCR', 'Deconvolved URL', 'Squashed URL', 'Final URL', 'Preview URL'
])
writer.writerows(out_rows)
sys.stderr.write(f"Written {len(out_rows)} rows\n")

# Made with Bob

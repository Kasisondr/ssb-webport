#!/usr/bin/env python3
"""Align the European ROM's reloc file ids onto the US file-id map.

The EU reloc table has more entries than the US one (2149 vs 2132 files), so an
EU file id is not a US file id. This script recovers the mapping by aligning
the two tables' declared decompressed-size sequences with a monotone LCS
(difflib), then reports how well the alignment holds.

Usage:
    python tools/reloc_align_probe.py [rom] [--write]
"""
import difflib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "BattleShip"
ENTRY = 12
EU_TABLE_ADDR = 0x262E20
EU_FILE_COUNT = 2149


def read_table(rom: bytes, addr: int, count: int):
    entries = []
    for i in range(count + 1):
        off = addr + i * ENTRY
        first, reloc_in, comp_words, reloc_ex, decomp_words = struct.unpack_from(">IHHHH", rom, off)
        entries.append({
            "compressed": bool(first >> 31),
            "data_off": first & 0x7FFFFFFF,
            "intern": reloc_in,
            "comp_bytes": comp_words * 4,
            "extern": reloc_ex,
            "decomp_bytes": decomp_words * 4,
        })
    return entries


def read_us_yamls():
    """{file_id: (name, path, decompressed_size)} from yamls/us."""
    out = {}
    for path in sorted((ENGINE / "yamls" / "us").glob("reloc_*.yml")):
        text = path.read_text()
        for block in text.split("\n\n"):
            m = re.search(r"file_id:\s*(\d+)", block)
            s = re.search(r"decompressed_size:\s*0x([0-9A-Fa-f]+)", block)
            name = re.search(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$", block, re.M)
            if m and s and name:
                out[int(m.group(1))] = (name.group(1), path.stem, int(s.group(1), 16))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    rom_path = Path(args[0]) if args else ROOT.parent / "Super Smash Bros. (Europe) (En,Fr,De).z64"
    rom = rom_path.read_bytes()
    print(f"ROM {rom_path.name}: {len(rom)} bytes, country {chr(rom[0x3E])!r}, code {rom[0x3B:0x3F].decode('latin1')}")

    eu = read_table(rom, EU_TABLE_ADDR, EU_FILE_COUNT)
    us = read_us_yamls()
    us_ids = sorted(us)
    us_sizes = [us[i][2] for i in us_ids]
    eu_sizes = [e["decomp_bytes"] for e in eu[:EU_FILE_COUNT]]

    sm = difflib.SequenceMatcher(None, us_sizes, eu_sizes, autojunk=False)
    eu_id_by_us_id = {}
    opcode_summary = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        opcode_summary[tag] = opcode_summary.get(tag, 0) + (i2 - i1)
        if tag == "equal":
            for k in range(i2 - i1):
                eu_id_by_us_id[us_ids[i1 + k]] = j1 + k

    matched = len(eu_id_by_us_id)
    print(f"alignment: {matched}/{len(us_ids)} US ids anchored to an EU id "
          f"({100.0 * matched / len(us_ids):.2f}%)")
    print(f"opcodes (US ids covered): {opcode_summary}")

    # A named US id that never got anchored is a hole; report the run structure.
    holes = [i for i in us_ids if i not in eu_id_by_us_id]
    print(f"unaligned US ids: {len(holes)}")
    runs = []
    for i in holes:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for r in runs[:20]:
        lo, hi = r[0], r[-1]
        before = eu_id_by_us_id.get(lo - 1)
        after = eu_id_by_us_id.get(hi + 1)
        print(f"  hole {lo}..{hi} ({len(r)} ids) between eu {before} and {after}")

    # Sanity: offsets must stay monotone in the EU id space.
    ok = True
    prev = -1
    for i in us_ids:
        e = eu_id_by_us_id.get(i)
        if e is None or e < prev:
            ok = False
            break
        prev = e
    print(f"monotone eu_id_by_us_id: {ok}")

    if write:
        out = ROOT / "tools" / "eu_file_id_map.json"
        out.write_text(json.dumps({
            "eu_table_addr": EU_TABLE_ADDR,
            "eu_file_count": EU_FILE_COUNT,
            "eu_id_by_us_id": [eu_id_by_us_id.get(i, -1) for i in us_ids],
        }, indent=1) + "\n")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()

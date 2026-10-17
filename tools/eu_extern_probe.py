#!/usr/bin/env python3
"""Do EU extern references ever point at files the US table does not have?

Extern file ids are stored in the ROM between one file's compressed data and
the next file's data (see torch SSB64::RelocFactory). The port resolves them as
US file ids, so an EU-only (inserted) target would have no US resource to load.

Usage: python tools/eu_extern_probe.py [rom]
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = 12
TABLE_ADDR = 0x262E20
COUNT = 2149
DATA_START = TABLE_ADDR + (COUNT + 1) * ENTRY


def main():
    rom_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "Super Smash Bros. (Europe) (En,Fr,De).z64"
    rom = rom_path.read_bytes()
    mp = json.loads((ROOT / "tools" / "eu_file_id_map.json").read_text())
    eu_by_us = mp["eu_id_by_us_id"]
    us_by_eu = {e: i for i, e in enumerate(eu_by_us) if e >= 0}
    inserted = [i for i in range(COUNT) if i not in us_by_eu]
    print(f"EU-only (inserted) file ids: {inserted}")

    entries = []
    for i in range(COUNT + 1):
        first, intern, comp_words, extern, decomp_words = struct.unpack_from(">IHHHH", rom, TABLE_ADDR + i * ENTRY)
        entries.append({"data_off": first & 0x7FFFFFFF, "comp": comp_words * 4, "decomp": decomp_words * 4})

    refs_to_inserted = 0
    refs_total = 0
    mapped_with_refs = {}
    for i in range(COUNT):
        e, nxt = entries[i], entries[i + 1]
        start = DATA_START + e["data_off"] + e["comp"]
        end = DATA_START + nxt["data_off"]
        ids = []
        if end > start:
            for k in range(start, end - 1, 2):
                ids.append((rom[k] << 8) | rom[k + 1])
        if ids:
            mapped_with_refs[i] = ids
            refs_total += len(ids)
            refs_to_inserted += sum(1 for x in ids if x in us_by_eu and False) or sum(1 for x in ids if x >= 0 and x not in us_by_eu)
    print(f"files with extern refs: {len(mapped_with_refs)}, total refs {refs_total}")
    print(f"references that land on an EU-only id: {refs_to_inserted}")
    # sanity: referenced ids should be < COUNT
    bad = [x for ids in mapped_with_refs.values() for x in ids if x >= COUNT]
    print(f"references out of range: {len(bad)} (first: {bad[:5]})")
    # Which inserted ids are referenced by anything?
    used = sorted({x for ids in mapped_with_refs.values() for x in ids if x not in us_by_eu})
    print(f"EU-only ids referenced: {used}")
    # spot check a mapped file: US 96,97,98 stage wallpapers
    for us_id in (96, 97, 98):
        eu_id = eu_by_us[us_id]
        ids = mapped_with_refs.get(eu_id, [])
        print(f"  US {us_id} -> EU {eu_id}: {len(ids)} extern refs -> US {[us_by_eu.get(x, -1) for x in ids]}")


if __name__ == "__main__":
    main()

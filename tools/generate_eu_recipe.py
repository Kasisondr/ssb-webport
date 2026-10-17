#!/usr/bin/env python3
"""Generate the European recipe (yamls/eu) from the US recipe + EU ROM table.

The native engine is compiled for one region's *code* (US), but its assets come
out of whatever ROM the player supplies. `tools/eu_reloc_map.py` recovers which
EU reloc file id holds each US asset; this tool turns that mapping into

  * BattleShip/yamls/eu/reloc_*.yml — same names as yamls/us, carrying the EU
    file_id/offset/size so Torch extracts the European ROM under the engine's
    resource paths,
  * BattleShip/yamls/eu/{particles,audio}.yml — the particle and audio segments,
    which sit outside the reloc table. The decompilation's splat config lists
    them for the US and JP ROMs only, so their European offsets and sizes are
    recovered from the ROM itself by tools/eu_globals.py (which also validates
    every segment before it is written), and
  * BattleShip/torch/src/factories/ssb64/RelocEuFileMap.h — the EU→US file id
    table Torch uses to translate external reloc references (the port resolves
    those as US ids) and honours EU files that have no US counterpart.

Usage:
    python tools/generate_eu_recipe.py [rom]
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

import eu_globals

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "BattleShip"
US_YAML_DIR = ENGINE / "yamls" / "us"
EU_YAML_DIR = ENGINE / "yamls" / "eu"
MAP_JSON = ROOT / "tools" / "eu_file_id_map.json"
MAP_HEADER = ENGINE / "torch" / "src" / "factories" / "ssb64" / "RelocEuFileMap.h"
GLOBAL_YAMLS = ("particles.yml", "audio.yml")
ENTRY_SIZE = 12
EU_TABLE_ADDR = 0x262E20
EU_FILE_COUNT = 2149
US_FILE_COUNT = 2132


def read_eu_table(rom):
    entries = []
    for i in range(EU_FILE_COUNT + 1):
        first, intern, comp_words, extern, decomp_words = struct.unpack_from(
            ">IHHHH", rom, EU_TABLE_ADDR + i * ENTRY_SIZE)
        entries.append({
            "compressed": bool(first >> 31),
            "data_off": first & 0x7FFFFFFF,
            "intern": intern,
            "comp_bytes": comp_words * 4,
            "extern": extern,
            "decomp_bytes": decomp_words * 4,
        })
    return entries


def identity_segments(offsets):
    """Segment table entries for offsets Torch would read as segmented addresses.

    Torch treats any offset whose top byte is 1..0x1F as a segmented address
    (IS_SEGMENTED in torch/src/factories/BaseFactory.h) and resolves it through
    the recipe's `:config: segments:` table before reading the ROM. The
    European audio banks live at 0x138CA40 and up, i.e. inside segment 0x13, so
    without an entry Torch logs "Segment data missing from game config" and
    reads from offset 0 — every one of those blobs would be a copy of the ROM
    header. Mapping the segment onto itself (`seg << 24`) keeps the offset the
    absolute ROM address it is.
    """
    segments = sorted({offset >> 24 for offset in offsets
                       if offset >= 0x01000000 and (offset >> 24) < 0x20})
    return [f"    - [0x{segment:02X}, 0x{segment << 24:08X}]" for segment in segments]


def write_global_recipe(name, layout, rom):
    """Rewrite a US BLOB recipe with the European offsets and sizes.

    The US file is the source of the entry names, symbols and the comments that
    explain each segment; only the addresses change. An entry the derivation
    could not validate is dropped, which is safe because the engine loads those
    segments only when they are present (the audio bridge checks each load).
    """
    us_path = US_YAML_DIR / name
    lines = us_path.read_text(encoding="utf-8").splitlines()
    entry_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$")
    out = []
    written = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = entry_re.match(line)
        if match:
            entry = match.group(1)
            block = [line]
            index += 1
            while index < len(lines) and not entry_re.match(lines[index]):
                block.append(lines[index])
                index += 1
            if entry not in layout:
                continue
            offset, size = layout[entry]
            block = [re.sub(r"^(\s*offset:\s*)0x[0-9A-Fa-f]+$", rf"\g<1>0x{offset:X}", b)
                     if b.strip().startswith("offset:") else b for b in block]
            block = [re.sub(r"^(\s*size:\s*)0x[0-9A-Fa-f]+$", rf"\g<1>0x{size:X}", b)
                     if b.strip().startswith("size:") else b for b in block]
            out.extend(block)
            written.append(entry)
            continue
        out.append(line)
        index += 1
    text = "\n".join(out) + "\n"
    extra_segments = identity_segments(offset for offset, _size in layout.values())
    if extra_segments:
        anchor = "    - [0x00, 0x000000]\n"
        if anchor not in text:
            raise SystemExit(f"{name}: no segment table to extend")
        text = text.replace(anchor, anchor + "\n".join(extra_segments) + "\n", 1)
    # The US files explain where their addresses come from; say where the
    # European ones come from instead.
    derived = ("# Offsets derived from the European ROM by tools/eu_globals.py: there is no\n"
               "# European splat config, so every segment is validated against its own\n"
               "# structures before it is written.")
    text = text.replace("# ROM addresses from splat config (smashbrothers.us.yaml).", derived)
    text = text.replace("# ROM addresses from splat config (smashbrothers.us.yaml)", derived)
    text = text.replace("# Auto-generated by tools/generate_yamls.py",
                        "# Auto-generated by tools/generate_eu_recipe.py")
    with (EU_YAML_DIR / name).open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return written


def parse_us_yamls():
    """[(path, [entry dicts])] with the raw fields of every US entry."""
    out = []
    for path in sorted(US_YAML_DIR.glob("reloc_*.yml")):
        text = path.read_text(encoding="utf-8")
        header = text.split("\n\n:config:", 1)[0]
        entries = []
        for block in text.split("\n\n:config:", 1)[1].split("\n\n")[1:]:
            block = block.strip("\n")
            if not block:
                continue
            name = block.split(":", 1)[0].strip()
            entries.append({
                "name": name,
                "file_id": int(re.search(r"file_id:\s*(\d+)", block).group(1)),
                "symbol": re.search(r"symbol:\s*(\S+)", block).group(1),
            })
        out.append((path, header, entries))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", nargs="?", default=str(ROOT.parent / "Super Smash Bros. (Europe) (En,Fr,De).z64"))
    args = ap.parse_args()
    rom = Path(args.rom).read_bytes()
    if chr(rom[0x3E]) != "P" or rom[0x3B:0x3F] != b"NALP":
        raise SystemExit("expected the European (NALP) ROM")

    table = read_eu_table(rom)
    data_start = EU_TABLE_ADDR + (EU_FILE_COUNT + 1) * ENTRY_SIZE
    mapping = json.loads(MAP_JSON.read_text())
    eu_by_us = mapping["eu_id_by_us_id"]
    assert len(eu_by_us) == US_FILE_COUNT, "mapping must cover every US file id"

    EU_YAML_DIR.mkdir(parents=True, exist_ok=True)
    for old in EU_YAML_DIR.glob("reloc_*.yml"):
        old.unlink()

    written = entries_total = 0
    for path, header, entries in parse_us_yamls():
        header = header.replace("# Auto-generated by tools/generate_yamls.py",
                                "# Auto-generated by tools/generate_eu_recipe.py")
        lines = [header, "", ":config:", "  segments:", "    - [0x00, 0x000000]", ""]
        blocks = []
        for entry in entries:
            eu_id = eu_by_us[entry["file_id"]]
            assert eu_id >= 0, f"US file {entry['file_id']} has no EU id"
            e, nxt = table[eu_id], table[eu_id + 1]
            offset = data_start + e["data_off"]
            size = nxt["data_off"] - e["data_off"]
            blocks.append("\n".join([
                f"{entry['name']}:",
                "  type: SSB64:RELOC",
                f"  offset: 0x{offset:X}",
                f"  size: 0x{size:X}",
                f"  symbol: {entry['symbol']}",
                f"  file_id: {eu_id}",
                f"  # compressed: {e['compressed']}",
                f"  # decompressed_size: 0x{e['decomp_bytes']:X}",
            ]))
        with (EU_YAML_DIR / path.name).open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n" + "\n\n".join(blocks) + "\n")
        written += 1
        entries_total += len(entries)

    # Particle and audio segments: outside the reloc table, so their addresses
    # come from the ROM's own structures rather than any offset table.
    segments, _facts, notes = eu_globals.derive(rom)
    layout = {name: (offset, size) for name, offset, size in segments}
    for line in notes:
        print(f"  {line}")
    for name in GLOBAL_YAMLS:
        written_entries = write_global_recipe(name, layout, rom)
        print(f"wrote yamls/eu/{name} ({len(written_entries)} segments)")

    us_id_by_eu = [0xFFFF] * EU_FILE_COUNT
    for us_id, eu_id in enumerate(eu_by_us):
        if eu_id >= 0:
            us_id_by_eu[eu_id] = us_id
    body = "\n".join(
        "\t" + ", ".join(f"0x{v:04X}" for v in us_id_by_eu[i:i + 16]) + ","
        for i in range(0, EU_FILE_COUNT, 16))
    with MAP_HEADER.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"""#pragma once

// Auto-generated by tools/generate_eu_recipe.py — do not edit by hand.
//
// European (NALP) reloc file ids do not match the US (NALE) ids the port's
// game code uses: the EU table carries 2149 files against the US 2132, with
// released-language variants inserted next to the files they localise.
// kUsIdByEuId translates an EU file id back to its US counterpart (0xFFFF for
// the EU-only files), which is what external reloc references need so the
// engine can look them up in gRelocFileTable[].

#include <cstdint>

namespace SSB64 {{

static constexpr uint32_t kEuRelocFileCount = {EU_FILE_COUNT};

static const uint16_t kUsIdByEuId[kEuRelocFileCount] = {{
{body}
}};

}} // namespace SSB64
""")

    print(f"wrote {written} yamls/eu files ({entries_total} entries) and {MAP_HEADER.name}")
    print(f"EU-only ids: {[i for i, v in enumerate(us_id_by_eu) if v == 0xFFFF]}")


if __name__ == "__main__":
    sys.exit(main())

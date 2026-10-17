#!/usr/bin/env python3
"""Recover the EU ROM's reloc file ids for the US file-id/name table.

The European ROM ships 2149 reloc files where the US build has 2132, so the
numeric file ids are not interchangeable. Both tables are ordered by the same
underlying asset list, so the ids differ only by localized files that were
added (or re-laid-out). This tool:

  1. reads the EU reloc table straight from the ROM,
  2. decompresses every entry and walks its internal/external reloc chains
     (the same walk tools/examine_reloc_files.py does for the US ROM),
  3. aligns the US fingerprint sequence (intern ptrs, extern ptrs, size)
     against the EU one with a monotone dynamic-programming alignment,

so the engine can map a US file id to the EU id holding the same asset.

Usage:
    python tools/eu_reloc_map.py [rom] [--write]

--write emits tools/eu_file_id_map.json (used by the launcher's ROM probe and
by the port's runtime asset derivation).
"""
import argparse
import ctypes
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "BattleShip"
ENTRY_SIZE = 12
EU_TABLE_ADDR = 0x262E20
EU_FILE_COUNT = 2149
US_FILE_COUNT = 2132


def build_vpk0():
    src = ENGINE / "torch" / "lib" / "libvpk0" / "vpk0.c"
    out = Path(tempfile.mkdtemp(prefix="vpk0_eu_")) / "libvpk0.dylib"
    for compiler in ("clang", "cc", "gcc"):
        try:
            subprocess.run([compiler, "-O2", "-shared", "-fPIC", "-o", str(out), str(src)],
                           check=True, capture_output=True)
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    if not out.exists():
        raise SystemExit("could not build libvpk0")
    lib = ctypes.CDLL(str(out))
    lib.vpk0_decode.restype = ctypes.c_uint32
    lib.vpk0_decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    return lib


def read_table(rom, addr, count):
    entries = []
    for i in range(count + 1):
        off = addr + i * ENTRY_SIZE
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


def walk_chain(words, start):
    slots = []
    cur = start
    while cur != 0xFFFF and cur < len(words):
        word = words[cur]
        slots.append(cur)
        cur = (word >> 16) & 0xFFFF
    return slots


def analyze(lib, data, intern, extern):
    n = len(data) // 4
    words = struct.unpack(f">{n}I", data[: n * 4]) if n else ()
    i_slots = walk_chain(words, intern) if intern != 0xFFFF else []
    e_slots = walk_chain(words, extern) if extern != 0xFFFF else []
    return len(i_slots), len(e_slots)


def eu_stats(rom):
    lib = build_vpk0()
    entries = read_table(rom, EU_TABLE_ADDR, EU_FILE_COUNT)
    data_start = EU_TABLE_ADDR + (EU_FILE_COUNT + 1) * ENTRY_SIZE
    stats = []
    for i in range(EU_FILE_COUNT):
        e = entries[i]
        raw = rom[data_start + e["data_off"]: data_start + e["data_off"] + e["comp_bytes"]]
        size = e["decomp_bytes"]
        if size == 0:
            stats.append({"intern": 0, "extern": 0, "size": 0, "ok": True})
            continue
        if e["compressed"]:
            dst = ctypes.create_string_buffer(size)
            src = ctypes.create_string_buffer(bytes(raw), max(len(raw), 1))
            written = lib.vpk0_decode(src, len(raw), dst, size)
            if written == 0:
                stats.append({"intern": 0, "extern": 0, "size": size, "ok": False})
                continue
            data = dst.raw[:size]
        else:
            data = raw[:size]
        intern, extern = analyze(lib, data, e["intern"], e["extern"])
        stats.append({"intern": intern, "extern": extern, "size": size, "ok": True,
                      "data_off": e["data_off"]})
    return stats


def us_fingerprints():
    sizes = {}
    for path in sorted((ENGINE / "yamls" / "us").glob("reloc_*.yml")):
        for block in path.read_text().split("\n\n"):
            m = re.search(r"file_id:\s*(\d+)", block)
            s = re.search(r"decompressed_size:\s*0x([0-9A-Fa-f]+)", block)
            name = re.search(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$", block, re.M)
            if m and s and name:
                sizes[int(m.group(1))] = (int(s.group(1), 16), name.group(1), path.stem)
    csv = {}
    for line in (ENGINE / "tools" / "reloc_file_analysis.csv").read_text().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 6 and parts[1] == "ok":
            csv[int(parts[0])] = (int(parts[4]), int(parts[5]))  # intern, extern
    out = {}
    for fid, (size, name, stem) in sizes.items():
        intern, extern = csv.get(fid, (None, None))
        out[fid] = {"size": size, "name": name, "stem": stem, "intern": intern, "extern": extern}
    return out


def score(us, eu):
    """Similarity of a US fingerprint and an EU fingerprint (higher is better)."""
    s = 0
    if us["intern"] is not None and us["intern"] == eu["intern"]:
        s += 4
    if us["extern"] is not None and us["extern"] == eu["extern"]:
        s += 3
    if us["size"] == eu["size"]:
        s += 4
    elif us["size"] and eu["size"]:
        ratio = max(us["size"], eu["size"]) / min(us["size"], eu["size"])
        if ratio <= 1.35:
            s += 1
    return s


def align(us_ids, us, eu, band=40):
    """Monotone alignment (needleman-wunsch, banded) returning {us_id: eu_id}."""
    n, m = len(us_ids), len(eu)
    NEG = -10**9
    # dp[i][j] = best score aligning us_ids[:i] with eu[:j]
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    GAP = -3
    for i in range(n + 1):
        lo = max(0, i - band)
        hi = min(m, i + band)
        for j in range(lo, hi + 1):
            if i == 0 and j == 0:
                continue
            best, arg = NEG, 0
            if i > 0 and j > 0:
                v = dp[i - 1][j - 1] + score(us[us_ids[i - 1]], eu[j - 1])
                if v > best:
                    best, arg = v, 1
            if i > 0:
                v = dp[i - 1][j] + GAP
                if v > best:
                    best, arg = v, 2
            if j > 0:
                v = dp[i][j - 1] + GAP
                if v > best:
                    best, arg = v, 3
            dp[i][j] = best
            back[i][j] = arg
    mapping = {}
    i, j = n, m
    while i > 0 or j > 0:
        arg = back[i][j]
        if arg == 1:
            mapping[us_ids[i - 1]] = j - 1
            i, j = i - 1, j - 1
        elif arg == 2:
            i -= 1
        else:
            j -= 1
    return mapping, dp[n][m]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", nargs="?", default=str(ROOT.parent / "Super Smash Bros. (Europe) (En,Fr,De).z64"))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    rom = Path(args.rom).read_bytes()
    print(f"ROM {Path(args.rom).name}: country {chr(rom[0x3E])!r} code {rom[0x3B:0x3F].decode('latin1')}")

    # Always re-read the EU table: a cached CSV would silently go stale if the
    # ROM or the reader changed, and the walk only takes a couple of seconds.
    eu = eu_stats(rom)
    cand = ROOT / "tools" / "eu_reloc_file_analysis.csv"
    cand.write_text("id,intern,extern,size,data_off,ok\n" + "\n".join(
        f"{i},{s['intern']},{s['extern']},{s['size']},{s.get('data_off', 0)},{1 if s['ok'] else 0}"
        for i, s in enumerate(eu)) + "\n")
    print(f"wrote {cand}")

    us = us_fingerprints()
    us_ids = sorted(us)
    mapping, best = align(us_ids, us, eu)
    exact = sum(1 for i in us_ids
                if i in mapping
                and us[i]["intern"] == eu[mapping[i]]["intern"]
                and us[i]["extern"] == eu[mapping[i]]["extern"])
    size_same = sum(1 for i in us_ids if i in mapping and us[i]["size"] == eu[mapping[i]]["size"])
    matched = len(mapping)
    print(f"aligned {matched}/{len(us_ids)} US ids (score {best})")
    print(f"  structural fingerprint match: {exact}/{matched} ({100.0*exact/matched:.2f}%)")
    print(f"  identical decompressed size : {size_same}/{matched} ({100.0*size_same/matched:.2f}%)")
    # The EU table should be the US table with localized files inserted, i.e.
    # a non-decreasing eu_id - us_id step function whose total rise equals the
    # file-count difference. Print the runs so the insertion points are visible.
    runs = []
    for i in us_ids:
        d = mapping.get(i, -1) - i
        if runs and runs[-1][2] == d and runs[-1][1] == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i, d])
    print(f"  eu_id - us_id runs ({len(runs)}):")
    for lo, hi, d in runs:
        print(f"    us {lo:4d}..{hi:4d}  +{d:2d}   ({us[lo]['stem']}/{us[lo]['name']})")
    total_rise = sum(max(0, runs[k + 1][2] - runs[k][2]) for k in range(len(runs) - 1))
    monotone = all(runs[k][2] <= runs[k + 1][2] for k in range(len(runs) - 1))
    print(f"  step function total rise {total_rise} (EU-US file count delta {EU_FILE_COUNT - US_FILE_COUNT}), monotone: {monotone}")

    # Which files disagree with their US size? Localized content is expected to.
    print("  size mismatches under this mapping:")
    for i in us_ids:
        if i in mapping and us[i]["size"] != eu[mapping[i]]["size"]:
            print(f"    us {i:4d} -> eu {mapping[i]:4d}  us={us[i]['size']:#x} eu={eu[mapping[i]]['size']:#x}"
                  f"  {us[i]['stem']}/{us[i]['name']}")

    if args.write:
        out = ROOT / "tools" / "eu_file_id_map.json"
        out.write_text(json.dumps({
            "eu_table_addr": EU_TABLE_ADDR,
            "eu_file_count": EU_FILE_COUNT,
            "eu_data_start": EU_TABLE_ADDR + (EU_FILE_COUNT + 1) * ENTRY_SIZE,
            "eu_id_by_us_id": [mapping.get(i, -1) for i in us_ids],
        }, indent=1) + "\n")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()

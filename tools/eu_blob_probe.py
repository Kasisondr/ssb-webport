#!/usr/bin/env python3
"""Locate the audio + particle ROM segments in the European ROM.

Those segments sit outside the LBReloc file table and the decomp's splat config
that lists them (smashbrothers.us.yaml / .jp.yaml) has no European counterpart.
Two independent signatures find them:

  1. the game's audio settings table (dSYAudioPublicSettings) holds the segment
     starts back to back, so a run of words whose differences are the three
     region-stable segment sizes (music sbk, SFX ctl, SFX tbl) pins the region,
  2. S1_music_sbk is an ALSeqFile: s16 count, then (u32 offset, s16 len) pairs
     whose last entry ends exactly at the segment size.

Both are content-based, so they identify the region in a ROM whose addresses are
unknown. Sizes for the segments after the SFX group are then derived from the
structures themselves (wave-table extents, pointer-array maxima) and reported
next to the US sizes for comparison.

Usage: python3 tools/eu_blob_probe.py [rom path]
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "BattleShip"
DEFAULT_ROM = ROOT.parent / "Super Smash Bros. (Europe) (En,Fr,De).z64"

# Region-stable segments, in ROM order, with their US sizes (yamls/us/audio.yml).
STABLE = [
    ("S1_music_sbk", 0x26E10),
    ("B1_sounds1_ctl", 0x6720),
    ("B1_sounds1_tbl", 0x116970),
]
US = {name: size for name, size in STABLE}
US["B1_sounds2_ctl"] = 0xFBA0
US["B1_sounds2_tbl"] = 0x2DC1E0
US["fgm_unk"] = 0x820
US["fgm_tbl"] = 0x2DD0
US["fgm_ucd"] = 0x4B20
US_MUSIC = 0xB277B0  # US S1_music_sbk, the anchor every other US offset shares a shift with


def al_seq_file(rom, off, size):
    """Parse an ALSeqFile at `off`; return the entries or None."""
    if off + 2 > len(rom):
        return None
    count = struct.unpack_from(">h", rom, off)[0]
    if not 0 < count <= 400:
        return None
    entries = []
    for i in range(count):
        o, ln = struct.unpack_from(">Ih", rom, off + 2 + i * 6)
        if ln <= 0 or o + ln > size:
            return None
        entries.append((o, ln))
    if not entries:
        return None
    end = max(o + ln for o, ln in entries)
    if end != size:
        return None
    if sorted(o for o, _ in entries) != [o for o, _ in entries]:
        return None
    return entries


def al_bank_file(rom, off, size):
    """Parse an ALBankFile header at `off`; return (revision, bank offsets)."""
    if off + 4 > len(rom):
        return None
    revision, banks = struct.unpack_from(">hh", rom, off)
    if not 0 <= revision <= 8 or not 0 < banks <= 64:
        return None
    if 4 + banks * 4 > size:
        return None
    offs = [struct.unpack_from(">I", rom, off + 4 + i * 4)[0] for i in range(banks)]
    if any(o % 4 or o >= size for o in offs):
        return None
    if sorted(offs) != offs:
        return None
    return revision, offs


def scan_settings_table(rom):
    """Signature 1: consecutive words differing by the stable segment sizes."""
    words = struct.unpack(f">{len(rom) // 4}I", rom[: len(rom) // 4 * 4])
    sizes = [s for _, s in STABLE]
    hits = []
    for i in range(len(words) - 8):
        diffs = []
        for k in range(8):
            d = words[i + k + 1] - words[i + k]
            if d > 0:
                diffs.append(d)
        if diffs[:3] == sizes:
            hits.append((i, words[i]))
    return hits


def scan_music_sbk(rom):
    """Signature 2: an ALSeqFile whose sequences exactly fill 0x26E10 bytes."""
    size = US["S1_music_sbk"]
    hits = []
    for off in range(0, len(rom) - size, 4):
        if al_seq_file(rom, off, size):
            hits.append(off)
    return hits


def main():
    rom_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROM
    rom = rom_path.read_bytes()
    print(f"ROM {rom_path.name}: {len(rom)} bytes (0x{len(rom):X})")

    table = scan_settings_table(rom)
    print(f"\n[1] audio settings table candidates: {len(table)}")
    for word_index, value in table[:5]:
        print(f"    file 0x{word_index * 4:X}: first pointer 0x{value:X}")

    sbk_hits = scan_music_sbk(rom)
    print(f"\n[2] ALSeqFile filling exactly 0x{US['S1_music_sbk']:X}: {len(sbk_hits)}")
    for off in sbk_hits[:5]:
        count = struct.unpack_from(">h", rom, off)[0]
        print(f"    music sbk 0x{off:X}: {count} sequences")

    # Prefer the ALSeqFile hit that also has a parseable bank file right after.
    anchor = None
    for off in sbk_hits:
        ctl = off + US["S1_music_sbk"]
        if al_bank_file(rom, ctl, US["B1_sounds1_ctl"]):
            if anchor is None:
                anchor = off
            print(f"    -> 0x{off:X} is followed by an ALBankFile at 0x{ctl:X} (revision "
                  f"{al_bank_file(rom, ctl, US['B1_sounds1_ctl'])[0]})")
    if anchor is None:
        print("\nno anchored candidate: cannot place the region")
        return 1

    delta = anchor - US_MUSIC
    print(f"\nanchor 0x{anchor:X}; shift against the US layout = "
          f"{'-' if delta < 0 else '+'}0x{abs(delta):X}")
    for name, size in STABLE:
        offset = {n: s for n, s in STABLE}
        us_off = US_MUSIC + STABLE[[n for n, _ in STABLE].index(name)][1] * 0
        # US starts: music, then +0x26E10, then +0x6720
        base = US_MUSIC + (0 if name == "S1_music_sbk" else
                           US["S1_music_sbk"] + (0 if name == "B1_sounds1_ctl" else US["B1_sounds1_ctl"]))
        print(f"  {name}: EU 0x{base + delta:X} (US 0x{base:X}, size 0x{size:X})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

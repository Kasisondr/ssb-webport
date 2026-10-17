#!/usr/bin/env python3
"""Locate the European ROM's non-reloc segments: audio banks and particle banks.

The US and JP offsets for these segments come from the decompilation's splat
config (smashbrothers.{us,jp}.yaml via tools/generate_yamls.py). There is no
European splat config, so the European offsets have to be recovered from the
ROM itself:

  * the LBReloc data region ends where the global (audio + particle) data
    region begins, and both regions keep a fixed per-segment layout in every
    region — the audio/particle segments hold no localized text, so their sizes
    agree between the US and JP ROMs (verified against yamls/jp) and the
    European ROM has the same ones. The reloc table's sentinel entry gives the
    European data end exactly, which anchors the region;
  * every segment then has to parse under the layouts the engine itself uses
    (port/bridge/particle_bank_bridge.cpp, port/bridge/audio_bridge.cpp): the
    script/texture banks as count + offset tables feeding typed records, the
    sequence bank as an ALSeqFile whose sequences exactly fill the segment, and
    the instrument banks as ALBankFiles whose wave tables index the matching TBL
    and whose own extent matches the declared size.

So the European layout is derived, not assumed: tools/generate_eu_recipe.py
writes it out only if every segment validates.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "BattleShip"
US_YAML_DIR = ENGINE / "yamls" / "us"

# European LBReloc table (see tools/eu_reloc_map.py).
EU_TABLE_ADDR = 0x262E20
EU_FILE_COUNT = 2149
ENTRY_SIZE = 12
# Alignment the ROM's build pipeline leaves between the reloc data region and
# the global data region; the anchor search tolerates more than this.
ANCHOR_SEARCH_SPAN = 0x1000
# The audio segments are consecutive (each bank is followed by its sample data),
# so a short window finds the next bank's magic.
BANK_SEARCH_SPAN = 0x100
# Bound used only while walking a bank's structures: it has to be generous
# enough for the largest bank, the walk itself bounds every field to it.
BANK_FILE_BOUND = 0x200000

# The audio segments stamp their format into the `revision` field as two ASCII
# characters, which the engine's loaders pass through untested: "S1" marks an
# ALSeqFile (music sequences), "B1" an ALBankFile (instrument banks).
SEQ_MAGIC = 0x5331  # "S1"
BANK_MAGIC = 0x4231  # "B1"


class LayoutError(RuntimeError):
    """A candidate layout did not validate against the ROM."""


def read_blob_yaml(path):
    """[(name, offset, size)] in file order from a generated BLOB recipe."""
    entries = []
    name, buf = None, []

    def flush():
        if name is None:
            return
        text = "\n".join(buf)
        off = re.search(r"offset:\s*0x([0-9A-Fa-f]+)", text)
        size = re.search(r"size:\s*0x([0-9A-Fa-f]+)", text)
        if off and size:
            entries.append((name, int(off.group(1), 16), int(size.group(1), 16)))

    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$", line)
        if match:
            flush()
            name, buf = match.group(1), []
        else:
            buf.append(line)
    flush()
    return entries


def us_layout():
    """The US particle and audio segments, in ROM order, with a contiguity check."""
    particles = read_blob_yaml(US_YAML_DIR / "particles.yml")
    audio = read_blob_yaml(US_YAML_DIR / "audio.yml")
    particles.sort(key=lambda e: e[1])
    audio.sort(key=lambda e: e[1])
    anchor = particles[0][1]
    span = audio[0][1] - anchor
    if sum(size for _, _, size in particles) != span:
        raise LayoutError(
            "the US recipe is not contiguous: particle sizes sum to "
            f"0x{sum(size for _, _, size in particles):X} but the music bank starts "
            f"0x{span:X} after the first particle bank")
    return particles, audio, anchor, span


US_AUDIO = {name: size for name, _offset, size in us_layout()[1]}
US_FGM = {name: US_AUDIO[name] for name in ("fgm_unk", "fgm_tbl", "fgm_ucd")}


def eu_data_region_end(rom, table_addr=EU_TABLE_ADDR, count=EU_FILE_COUNT):
    """Absolute ROM offset one past the last LBReloc file's data."""
    data_start = table_addr + (count + 1) * ENTRY_SIZE
    sentinel = struct.unpack_from(">I", rom, table_addr + count * ENTRY_SIZE)[0]
    return data_start + (sentinel & 0x7FFFFFFF)


# ---------------------------------------------------------------------------
# Segment validators. Each returns a dict of facts about the segment or raises
# LayoutError; the field layouts mirror the engine's loaders exactly.
# ---------------------------------------------------------------------------

def parse_script_bank(rom, off, size):
    """Particle script bank: s32 count, u32 offsets[], LBScript records."""
    if off < 0 or off + 4 > len(rom):
        raise LayoutError(f"script bank at 0x{off:X} is outside the ROM")
    count = struct.unpack_from(">i", rom, off)[0]
    if not 0 < count <= 1024:
        raise LayoutError(f"script bank at 0x{off:X}: count {count} is not 1..1024")
    table_end = 4 + count * 4
    if table_end > size:
        raise LayoutError(f"script bank at 0x{off:X}: {count} offsets overrun 0x{size:X}")
    offsets = [struct.unpack_from(">I", rom, off + 4 + i * 4)[0] for i in range(count)]
    if offsets != sorted(offsets):
        raise LayoutError(f"script bank at 0x{off:X}: offset table is not ascending")
    if any(o < table_end or o + 0x30 > size for o in offsets):
        raise LayoutError(f"script bank at 0x{off:X}: a script header escapes 0x{size:X}")
    kinds = set()
    for o in offsets:
        kind, texture, gen_life, life = struct.unpack_from(">HHHH", rom, off + o)
        kinds.add(kind)
        if kind > 0x40 or texture > 0x200 or gen_life > 0x4000 or life > 0x4000:
            raise LayoutError(
                f"script bank at 0x{off:X}: script 0x{o:X} header looks wrong "
                f"(kind 0x{kind:X}, texture {texture}, lifetimes {gen_life}/{life})")
    return {"count": count, "table_end": table_end, "kinds": sorted(kinds)}


def parse_texture_bank(rom, off, size):
    """Particle texture bank: s32 count, u32 offsets[], LBTexture records."""
    if off < 0 or off + 4 > len(rom):
        raise LayoutError(f"texture bank at 0x{off:X} is outside the ROM")
    count = struct.unpack_from(">i", rom, off)[0]
    if not 0 < count <= 1024:
        raise LayoutError(f"texture bank at 0x{off:X}: count {count} is not 1..1024")
    table_end = 4 + count * 4
    if table_end > size:
        raise LayoutError(f"texture bank at 0x{off:X}: {count} offsets overrun 0x{size:X}")
    offsets = [struct.unpack_from(">I", rom, off + 4 + i * 4)[0] for i in range(count)]
    if offsets != sorted(offsets):
        raise LayoutError(f"texture bank at 0x{off:X}: offset table is not ascending")
    formats, sizes = set(), set()
    for o in offsets:
        if o < table_end or o + 0x18 > size:
            raise LayoutError(f"texture bank at 0x{off:X}: texture 0x{o:X} header escapes 0x{size:X}")
        entries, fmt, siz, width, height, flags = struct.unpack_from(">IiiiII", rom, off + o)
        formats.add(fmt)
        sizes.add(siz)
        if entries > 4096 or fmt not in (0, 1, 2, 3, 4) or siz not in (0, 1, 2, 3):
            raise LayoutError(
                f"texture bank at 0x{off:X}: texture 0x{o:X} has fmt {fmt} siz {siz} entries {entries}")
        if not 0 < width <= 1024 or not 0 < height <= 1024:
            raise LayoutError(
                f"texture bank at 0x{off:X}: texture 0x{o:X} is {width}x{height}")
        # fmt 2 (CI) carries `entries` pixel buffers plus one shared palette when
        # flags bit 0 is set, otherwise one palette per pixel buffer.
        total = entries + ((1 if flags & 1 else entries) if fmt == 2 else 0)
        if o + 0x18 + total * 4 > size:
            raise LayoutError(
                f"texture bank at 0x{off:X}: texture 0x{o:X} data[] overruns 0x{size:X}")
    return {"count": count, "table_end": table_end, "formats": sorted(formats)}


def parse_seq_file(rom, off, size):
    """ALSeqFile: s16 revision, s16 count, count * (u32 offset, s32 length)."""
    if off < 0 or off + 4 > len(rom):
        raise LayoutError(f"sequence bank at 0x{off:X} is outside the ROM")
    revision, count = struct.unpack_from(">HH", rom, off)
    if revision != SEQ_MAGIC:
        raise LayoutError(f"sequence bank at 0x{off:X}: header magic 0x{revision:04X}")
    if not 0 < count <= 400:
        raise LayoutError(f"sequence bank at 0x{off:X}: count {count} is not 1..400")
    table_end = 4 + count * 8
    if table_end > size:
        raise LayoutError(f"sequence bank at 0x{off:X}: {count} sequences overrun 0x{size:X}")
    entries = [struct.unpack_from(">Ii", rom, off + 4 + i * 8) for i in range(count)]
    if [o for o, _ in entries] != sorted(o for o, _ in entries):
        raise LayoutError(f"sequence bank at 0x{off:X}: sequence table is not ascending")
    if any(length <= 0 or start + length > size for start, length in entries):
        raise LayoutError(f"sequence bank at 0x{off:X}: a sequence escapes 0x{size:X}")
    filled = max(start + length for start, length in entries)
    if filled > size:
        raise LayoutError(
            f"sequence bank at 0x{off:X}: sequences reach 0x{filled:X}, declared 0x{size:X}")
    return {"count": count, "revision": revision, "filled": filled, "slack": size - filled}


class _BankWalk:
    """Walks an ALBankFile, bounding every field to the segment and recording
    the furthest byte any structure reaches plus the extent of the TBL samples
    its wave tables point at."""

    def __init__(self, rom, base, size):
        self.rom, self.base, self.size = rom, base, size
        self.extent = 0
        self.sample_extent = 0
        self.sample_bases = []
        self.counts = {"banks": 0, "instruments": 0, "sounds": 0, "waves": 0}

    def _check(self, rel, length, what):
        if rel < 0 or rel + length > self.size:
            raise LayoutError(
                f"{what} at 0x{rel:X} (+0x{length:X}) escapes the 0x{self.size:X} segment")
        self.extent = max(self.extent, rel + length)

    def u8(self, rel):
        self._check(rel, 1, "byte")
        return self.rom[self.base + rel]

    def u16(self, rel):
        self._check(rel, 2, "halfword")
        return struct.unpack_from(">H", self.rom, self.base + rel)[0]

    def s16(self, rel):
        self._check(rel, 2, "halfword")
        return struct.unpack_from(">h", self.rom, self.base + rel)[0]

    def u32(self, rel):
        self._check(rel, 4, "word")
        return struct.unpack_from(">I", self.rom, self.base + rel)[0]

    def s32(self, rel):
        self._check(rel, 4, "word")
        return struct.unpack_from(">i", self.rom, self.base + rel)[0]

    def envelope(self, rel):
        self.s32(rel)
        self.s32(rel + 4)
        self.s32(rel + 8)
        self.u8(rel + 12)
        self.u8(rel + 13)

    def keymap(self, rel):
        for k in range(6):
            self.u8(rel + k)

    def book(self, rel):
        order, npred = self.s32(rel), self.s32(rel + 4)
        if not 0 < order <= 8 or not 0 < npred <= 8:
            raise LayoutError(f"ADPCM book at 0x{rel:X}: order {order}, predictors {npred}")
        self._check(rel, 8 + order * npred * 16, "ADPCM book")

    def loop(self, rel, adpcm):
        start, end = self.s32(rel), self.s32(rel + 4)
        self.s32(rel + 8)
        self._check(rel, 44 if adpcm else 12, "ADPCM loop" if adpcm else "raw loop")
        if not 0 <= start <= end:
            raise LayoutError(f"wave loop at 0x{rel:X}: {start}..{end}")

    def wave(self, rel):
        base, length = self.u32(rel), self.s32(rel + 4)
        wave_type, _flags = self.u8(rel + 8), self.u8(rel + 9)
        if wave_type not in (0, 1):
            raise LayoutError(f"wave table at 0x{rel:X}: type {wave_type}")
        if length <= 0:
            raise LayoutError(f"wave table at 0x{rel:X}: length {length}")
        loop_off = self.u32(rel + 12)
        if wave_type == 0:
            book_off = self.u32(rel + 16)
            if loop_off:
                self.loop(loop_off, True)
            if book_off:
                self.book(book_off)
        elif loop_off:
            self.loop(loop_off, False)
        self.sample_extent = max(self.sample_extent, base + length)
        self.sample_bases.append((base, length))
        self.counts["waves"] += 1

    def sound(self, rel):
        env, key, wave = self.u32(rel), self.u32(rel + 4), self.u32(rel + 8)
        for k in range(4):
            self.u8(rel + 12 + k)
        if env:
            self.envelope(env)
        if key:
            self.keymap(key)
        if wave:
            self.wave(wave)
        self.counts["sounds"] += 1

    def instrument(self, rel):
        for k in range(12):
            self.u8(rel + k)
        self.s16(rel + 12)
        sound_count = self.s16(rel + 14)
        # The 44.1 kHz sound-effect bank packs one instrument with hundreds of
        # sounds (475 in the European ROM), so the cap is generous.
        if not 0 <= sound_count <= 4096:
            raise LayoutError(f"instrument at 0x{rel:X}: {sound_count} sounds")
        self._check(rel, 16 + sound_count * 4, "instrument")
        for i in range(sound_count):
            sound = self.u32(rel + 16 + i * 4)
            if sound:
                self.sound(sound)
        self.counts["instruments"] += 1

    def bank(self, rel):
        inst_count = self.s16(rel)
        self.u8(rel + 2)
        self.u8(rel + 3)
        self.s32(rel + 4)
        percussion = self.u32(rel + 8)
        if not 0 <= inst_count <= 4096:
            raise LayoutError(f"bank at 0x{rel:X}: {inst_count} instruments")
        self._check(rel, 12 + inst_count * 4, "bank")
        if percussion:
            self.instrument(percussion)
        for i in range(inst_count):
            inst = self.u32(rel + 12 + i * 4)
            if inst:
                self.instrument(inst)
        self.counts["banks"] += 1

    def run(self):
        revision, bank_count = self.u16(0), self.s16(2)
        if revision != BANK_MAGIC:
            raise LayoutError(f"bank file header magic 0x{revision:04X}")
        if not 0 < bank_count <= 64:
            raise LayoutError(f"bank file holds {bank_count} banks")
        self._check(0, 4 + bank_count * 4, "bank file header")
        for i in range(bank_count):
            bank = self.u32(4 + i * 4)
            if bank:
                self.bank(bank)
        return self


    def sample_layout(self):
        """Sample banks are packed in base order; a jump means a wave table
        points outside the pair, so the packed extent is the trustworthy one."""
        packed, breaks = 0, 0
        for base, length in sorted(self.sample_bases):
            if base - packed > 0x10:
                breaks += 1
            packed = max(packed, _round_up(base + length, 4))
        return packed, breaks


def _round_up(value, alignment=0x10):
    return (value + alignment - 1) & ~(alignment - 1)


def parse_bank_file(rom, off, size):
    """ALBankFile: instrument bank whose wave tables index the paired TBL."""
    if off < 0 or off + 4 > len(rom):
        raise LayoutError(f"bank file at 0x{off:X} is outside the ROM")
    walk = _BankWalk(rom, off, size).run()
    packed, breaks = walk.sample_layout()
    return {"revision": struct.unpack_from(">H", rom, off)[0], "extent": walk.extent,
            "sample_extent": walk.sample_extent, "sample_packed": packed,
            "sample_breaks": breaks, "counts": walk.counts}


def parse_pointer_array(rom, off, size):
    """SYAudioPackage: s32 count followed by count ascending in-segment offsets."""
    if off < 0 or off + 4 > len(rom):
        raise LayoutError(f"pointer array at 0x{off:X} is outside the ROM")
    count = struct.unpack_from(">i", rom, off)[0]
    if not 0 < count <= 4096:
        raise LayoutError(f"pointer array at 0x{off:X}: count {count}")
    if 4 + count * 4 > size:
        raise LayoutError(f"pointer array at 0x{off:X}: {count} entries overrun 0x{size:X}")
    values = [struct.unpack_from(">I", rom, off + 4 + i * 4)[0] for i in range(count)]
    if values != sorted(values) or any(v >= size for v in values):
        raise LayoutError(f"pointer array at 0x{off:X}: entries are not ascending in-segment offsets")
    return {"count": count, "filled": 4 + count * 4, "first": values[0], "max": values[-1]}


def parse_raw(rom, off, size):
    """Sample data: an ADPCM byte stream with no structure of its own. Its
    extent is checked against the wave tables of the instrument bank it pairs
    with (see derive())."""
    if off < 0 or off + size > len(rom):
        raise LayoutError(f"sample data at 0x{off:X} (size 0x{size:X}) is outside the ROM")
    return {}


PARSERS = {"_scb": parse_script_bank, "_txb": parse_texture_bank, "_tbl": parse_raw}


def _parser_for(name):
    for suffix, parser in PARSERS.items():
        if name.endswith(suffix):
            return parser
    if name == "S1_music_sbk":
        return parse_seq_file
    if name.endswith("_ctl"):
        return parse_bank_file
    if name.startswith("fgm"):
        return parse_pointer_array
    raise LayoutError(f"no validator for {name}")


def validate(rom, segments):
    """Validate [(name, offset, size)] against the ROM; returns per-segment facts."""
    facts = {}
    for name, offset, size in segments:
        parser = _parser_for(name)
        try:
            facts[name] = parser(rom, offset, size)
        except LayoutError as error:
            raise LayoutError(f"{name} at 0x{offset:X} (size 0x{size:X}): {error}") from None
    return facts


def next_bank_file(rom, start, span):
    """First ALBankFile at or after `start`: the audio segments are stamped
    with their magic, so this finds the next one without any offset table."""
    for off in range(_round_up(start, 4), start + span, 4):
        if off + 4 > len(rom):
            break
        if struct.unpack_from(">H", rom, off)[0] != BANK_MAGIC:
            continue
        try:
            return off, parse_bank_file(rom, off, BANK_FILE_BOUND)
        except LayoutError:
            continue
    raise LayoutError(f"no instrument bank in 0x{start:X}..0x{start + span:X}")


def fgm_lookup_table(rom, start):
    """The FGM banks carry no magic and the first one has no count the engine
    reads, so the region is accepted only when the look-up table that follows it
    is self-describing: ascending offsets into the microcode that starts exactly
    where the table ends."""
    table = start + US_FGM["fgm_unk"]
    if table + 4 > len(rom):
        return None
    try:
        facts = parse_pointer_array(rom, table, US_FGM["fgm_ucd"])
    except LayoutError:
        return None
    return facts if facts["first"] == facts["filled"] else None


def derive(rom):
    """Derive the European global-data layout from the ROM.

    Returns (segments, facts, notes): segments are [(name, offset, size)] in ROM
    order, with the offset and size each segment actually occupies; facts are the
    per-segment parse results; notes record the cross-checks that succeeded.
    """
    particles_us, audio_us, anchor_us, span = us_layout()
    data_end = eu_data_region_end(rom)
    notes = [f"reloc data region ends at 0x{data_end:X}"]

    # The particle banks open the region and the music bank sits `span` further
    # on, so a candidate that satisfies both fixes every particle size against
    # the US recipe's (the segments hold no localized content).
    anchor = None
    music = None
    seq = None
    for candidate in range(data_end, data_end + ANCHOR_SEARCH_SPAN, 4):
        if candidate < 0 or candidate + span >= len(rom):
            break
        try:
            parse_script_bank(rom, candidate, particles_us[0][2])
            parse_texture_bank(rom, candidate + particles_us[0][2], particles_us[1][2])
            seq = parse_seq_file(rom, candidate + span, US_AUDIO["S1_music_sbk"])
        except LayoutError as error:
            notes.append(f"candidate 0x{candidate:X} rejected: {error}")
            continue
        anchor, music = candidate, candidate + span
        break
    if anchor is None:
        raise LayoutError(
            f"no offset in 0x{data_end:X}..0x{data_end + ANCHOR_SEARCH_SPAN:X} "
            "opens the particle banks and the music bank at the US distance:\n  "
            + "\n  ".join(notes))
    notes.append(f"global data region starts at 0x{anchor:X} "
                 f"({anchor - data_end} bytes after the reloc data)")

    segments, facts = [], {}
    for name, us_offset, size in particles_us:
        offset = anchor + (us_offset - anchor_us)
        facts[name] = _parser_for(name)(rom, offset, size)
        segments.append((name, offset, size))

    # Music sequences: the segment runs to the SFX bank's magic.
    ctl1, ctl1_facts = next_bank_file(rom, music + seq["filled"], BANK_SEARCH_SPAN)
    if ctl1 - music - seq["filled"] > 0x40:
        raise LayoutError(f"the music bank's sequences end at 0x{music + seq['filled']:X}"
                          f" but the SFX bank only starts at 0x{ctl1:X}")
    facts["S1_music_sbk"] = seq
    segments.append(("S1_music_sbk", music, ctl1 - music))

    # Each instrument bank is followed by the sample data its wave tables index;
    # the next bank's magic bounds that sample data.
    for ctl_name, tbl_name in (("B1_sounds1_ctl", "B1_sounds1_tbl"),
                               ("B1_sounds2_ctl", "B1_sounds2_tbl")):
        ctl = ctl1 if ctl_name == "B1_sounds1_ctl" else ctl2
        ctl_facts = ctl1_facts if ctl_name == "B1_sounds1_ctl" else ctl2_facts
        tbl = ctl + _round_up(ctl_facts["extent"])
        if tbl_name == "B1_sounds2_tbl":
            tbl_size = _round_up(ctl_facts["sample_extent"])
            if ctl_facts["sample_breaks"]:
                raise LayoutError(f"{ctl_name}: its sample banks are not contiguous, so the"
                                  f" paired sample data's extent is not trustworthy")
        else:
            ctl2, ctl2_facts = next_bank_file(rom, tbl + ctl_facts["sample_extent"],
                                              BANK_SEARCH_SPAN)
            tbl_size = ctl2 - tbl
            if not 0 <= tbl_size - ctl_facts["sample_extent"] <= 0x100:
                raise LayoutError(
                    f"{tbl_name}: the wave tables of {ctl_name} reach "
                    f"0x{ctl_facts['sample_extent']:X}, but the sample data would be "
                    f"0x{tbl_size:X} long")
        facts[ctl_name] = ctl_facts
        segments.append((ctl_name, ctl, tbl - ctl))
        segments.append((tbl_name, tbl, tbl_size))

    # The FGM banks close the region. Their sizes are the region-independent
    # ones the US and JP recipes share, which the look-up table confirms.
    fgm_start = tbl + tbl_size
    lookup = fgm_lookup_table(rom, fgm_start)
    if lookup:
        offset = fgm_start
        for name in ("fgm_unk", "fgm_tbl", "fgm_ucd"):
            # Only the look-up table has a structure the engine parses; the other
            # two are a parameter table and an n_audio microcode stream.
            facts[name] = lookup if name == "fgm_tbl" else {}
            segments.append((name, offset, US_FGM[name]))
            offset += US_FGM[name]
        notes.append("FGM banks follow the sample data; their look-up table is "
                     "self-describing at the expected offset")
    else:
        notes.append(f"FGM banks omitted: no self-describing look-up table at "
                     f"0x{fgm_start + US_FGM['fgm_unk']:X} (the engine loads them "
                     "only when present)")

    for name, offset, size in segments:
        fact = facts.get(name, {})
        detail = []
        if name.endswith("_scb"):
            detail.append(f"{fact['count']} scripts, kinds {fact['kinds'][:6]}")
        elif name.endswith("_txb"):
            detail.append(f"{fact['count']} textures, formats {fact['formats']}")
        elif name == "S1_music_sbk":
            detail.append(f"{fact['count']} sequences reaching 0x{fact['filled']:X} "
                          f"(0x{size - fact['filled']:X} of padding)")
        elif name.endswith("_ctl"):
            detail.append(f"{fact['counts']['banks']} banks, "
                          f"{fact['counts']['instruments']} instruments, "
                          f"{fact['counts']['sounds']} sounds, "
                          f"structures reach 0x{fact['extent']:X}, samples reach "
                          f"0x{fact['sample_extent']:X}")
            if fact["extent"] > size:
                raise LayoutError(f"{name} structures overrun the segment")
        elif name == "fgm_unk":
            detail.append("parameter table (no header the engine reads)")
        elif name == "fgm_tbl":
            detail.append(f"{fact['count']} entries reaching 0x{fact['max']:X}, "
                          f"the first pointing just past the table")
        elif name == "fgm_ucd":
            detail.append("n_audio microcode stream")
        elif name.endswith("_tbl"):
            ctl_facts = facts[name[: -len("tbl")] + "ctl"]
            detail.append(f"wave tables reach 0x{ctl_facts['sample_extent']:X} "
                          f"(0x{size - ctl_facts['sample_extent']:X} of tail)")
        else:
            detail.append("raw sample stream")
        notes.append(f"{name} at 0x{offset:X} (0x{size:X}): " + ", ".join(detail))
    return segments, facts, notes


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", nargs="?",
                        default=str(ROOT.parent / "Super Smash Bros. (Europe) (En,Fr,De).z64"))
    args = parser.parse_args()
    rom = Path(args.rom).read_bytes()
    segments, _facts, notes = derive(rom)
    for note in notes:
        print(note)
    print(f"\n{len(segments)} segments:")
    for name, offset, size in segments:
        print(f"  {name:<26} 0x{offset:07X}  0x{size:X}")


if __name__ == "__main__":
    main()

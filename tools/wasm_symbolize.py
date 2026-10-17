#!/usr/bin/env python3
"""Map a wasm stack trace's function indices to code ranges and referenced data.

The packaged engine wasm has no name section, so a V8 trace such as

    RuntimeError: memory access out of bounds
        at BattleShip.wasm:wasm-function[6687]:0x531ce3

can be read back into *code* (this tool) even though it cannot be read back
into *source*. The trick is that `llvm-objdump -d --no-show-raw-insn` prints
every function body in the module's function-index space order, and the
`0x...` in the V8 frame is the byte offset of the faulting instruction inside
the *code section as laid out in the file*. Parsing the code section's function
extents therefore gives an exact index -> [file offset] map, and the faulting
address selects one function.

    python3 tools/wasm_symbolize.py --wasm BattleShip/web-dist/BattleShip.wasm \
        --dis build/ssb64.dis 6687:0x531ce3 6825:0x557aef

Each frame is reported as `wasm-fn[N] 0x<start>-0x<end>` plus the printable
string literals and call targets its body references, which is normally enough
to recognise the function from the source tree.
"""
import argparse
import bisect
import re
from pathlib import Path


def read_uleb(buf, pos):
    value = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def sections(data):
    pos = 8
    out = []
    while pos < len(data):
        sid = data[pos]
        pos += 1
        size, pos = read_uleb(data, pos)
        out.append((sid, size, pos))
        pos += size
    return out


def defined_function_starts(data):
    """File offsets of every defined function body, in function-index order."""
    code = next(s for s in sections(data) if s[0] == 10)
    pos = code[2]
    count, pos = read_uleb(data, pos)
    starts = []
    for _ in range(count):
        size, body = read_uleb(data, pos)
        starts.append(body)
        pos = body + size
    starts.append(pos)
    return starts


def static_image(data, size=0x800000):
    """Apply the data section's active segments to a zeroed memory image."""
    seg = next(s for s in sections(data) if s[0] == 11)
    pos = seg[2]
    count, pos = read_uleb(data, pos)
    image = bytearray(size)
    for _ in range(count):
        flags, pos = read_uleb(data, pos)
        if flags != 0:
            break
        assert data[pos] == 0x41, 'unexpected data segment offset expression'
        offset, pos = read_uleb(data, pos + 1)
        assert data[pos] == 0x0B
        pos += 1
        length, pos = read_uleb(data, pos)
        image[offset:offset + length] = data[pos:pos + length]
        pos += length
    return image


def import_count(data):
    imp = next(s for s in sections(data) if s[0] == 2)
    count, _ = read_uleb(data, imp[2])
    return count


def load_disassembly(path):
    lines = Path(path).read_text(errors='replace').splitlines()
    addr_to_line = {}
    for i, line in enumerate(lines):
        m = re.match(r'^\s*([0-9a-f]+):', line)
        if m:
            addr_to_line.setdefault(int(m.group(1), 16), i)
    return lines, addr_to_line


def describe(frame, starts, imports, image, lines, addr_to_line):
    index, addr = frame
    ordinal = bisect.bisect_right(starts, addr) - 1
    lo, hi = starts[ordinal], starts[ordinal + 1]
    print(f'frame wasm-fn[{index}] @0x{addr:x} -> code 0x{lo:x}-0x{hi:x} '
          f'({hi - lo} bytes), index-space check {imports + ordinal}')
    body = [line for a, line in addr_to_line.items() if lo <= a < hi]
    body = [lines[i] for a, i in sorted(addr_to_line.items()) if lo <= a < hi]
    strings = []
    for line in body:
        m = re.search(r'i32\.const\t(\d+)', line)
        if not m:
            continue
        value = int(m.group(1))
        if 0x1000 <= value < len(image):
            text = bytes(image[value:value + 64]).split(b'\x00')[0]
            if len(text) >= 8 and all(32 <= c < 127 or c in (9, 10, 13) for c in text):
                strings.append((value, text[:70]))
    calls = sorted({int(m.group(1)) for line in body
                    for m in [re.search(r'call\t(\d+)', line)] if m})
    for value, text in strings[:14]:
        print(f'    str@0x{value:x}: {text!r}')
    print(f'    calls: {calls[:25]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--wasm', default='BattleShip/web-dist/BattleShip.wasm')
    parser.add_argument('--dis', default='build/ssb64.dis')
    parser.add_argument('frames', nargs='+', help='frames as INDEX:0xADDRESS')
    args = parser.parse_args()

    data = Path(args.wasm).read_bytes()
    starts = defined_function_starts(data)
    image = static_image(data)
    imports = import_count(data)
    lines, addr_to_line = load_disassembly(args.dis)
    for frame in args.frames:
        index, _, addr = frame.partition(':')
        describe((int(index), int(addr, 16)), starts, imports, image, lines, addr_to_line)


if __name__ == '__main__':
    main()

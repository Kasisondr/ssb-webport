"""Compare vertex-load boundaries and ordered triangle indices in actual GBI traces.

Usage: python3 tests/compare_triangle_traces.py scalar.gbi paired.gbi
Pointer addresses are deliberately excluded: different builds relocate allocations.
"""
import collections
import json
import re
import sys
from pathlib import Path


def decode(path):
    stream = []
    counts = collections.Counter()
    frames = []
    for line in Path(path).read_text().splitlines():
        if line.startswith('=== FRAME '):
            frames.append(line)
        match = re.search(r'\b(G_TRI1|G_TRI2|G_VTX)\b.*w0=([0-9A-Fa-f]+)\s+w1=([0-9A-Fa-f]+)', line)
        if not match:
            continue
        op, w0, w1 = match.groups()
        w0, w1 = int(w0, 16), int(w1, 16)
        counts[op] += 1
        if op == 'G_VTX':
            stream.append(('vertex_load', w0))
        else:
            for word in ([w0, w1] if op == 'G_TRI2' else [w0]):
                stream.append(('triangle', tuple(((word >> shift) & 255) // 2 for shift in (16, 8, 0))))
    assert frames and counts['G_VTX'] and counts['G_TRI1'] + counts['G_TRI2'], 'Empty or unrecognized trace'
    return stream, counts, frames


a, ac, af = decode(sys.argv[1])
b, bc, bf = decode(sys.argv[2])
assert af == bf, 'Different trace frames'
assert a == b, 'Triangle indices/order or vertex-load boundaries changed'
assert bc['G_TRI1'] + bc['G_TRI2'] < ac['G_TRI1'] + ac['G_TRI2'], 'Triangle command count did not decrease'
print(json.dumps({'equivalent': True, 'frames': af, 'triangles': ac['G_TRI1'] + 2 * ac['G_TRI2'],
                  'vertexLoads': ac['G_VTX'], 'before': dict(ac), 'after': dict(bc)}, indent=2))

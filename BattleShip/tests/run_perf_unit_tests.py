#!/usr/bin/env python3
"""Run the DL-range, mesh, and texture-buffer tests using a configured native build.
Usage: python3 tests/run_perf_unit_tests.py [build-us]
"""
import pathlib
import shlex
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
build = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'build-us')
if not build.is_absolute():
    build = root / build
commands = subprocess.check_output(
    ['ninja', '-C', str(build), '-t', 'commands', 'CMakeFiles/ssb64.dir/port/port_dl_ranges.cpp.o'], text=True)
command = next(line for line in commands.splitlines() if line.endswith('/port/port_dl_ranges.cpp'))
args = shlex.split(command)
with tempfile.TemporaryDirectory(prefix='opensmash-perf-tests-') as temporary:
    clean = []
    i = 0
    while i < len(args):
        if args[i] in ('-MT', '-MF', '-o'):
            i += 2
        elif args[i] in ('-MD', '-c'):
            i += 1
        else:
            clean.append(args[i])
            i += 1
    clean[-1] = str(root / 'tests/dl_range_gap_cache.cpp')
    executable = str(pathlib.Path(temporary) / 'dl-ranges')
    subprocess.run(clean + ['-UNDEBUG', '-o', executable], cwd=build, check=True)
    subprocess.run([executable], check=True)
    executable = str(pathlib.Path(temporary) / 'texture-upload-buffer')
    subprocess.run([args[0], '-std=c++17', '-Ilibultraship/include',
                    'tests/texture_upload_buffer.cpp', '-o', executable], cwd=root, check=True)
    subprocess.run([executable], check=True)
    executable = str(pathlib.Path(temporary) / 'mesh-cache')
    subprocess.run([args[0], '-std=c++17', 'tests/mesh_cache.cpp',
                    'third_party/meshoptimizer/allocator.cpp', 'third_party/meshoptimizer/vcacheoptimizer.cpp',
                    '-o', executable], cwd=root, check=True)
    subprocess.run([executable], check=True)

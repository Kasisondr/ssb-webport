#!/usr/bin/env python3
"""Rebuild the pinned native source port and its browser asset extractor.

Stages: patch -> engine (BattleShip.js/.wasm) -> torch (extractor) -> package.
`--only engine,torch,package` re-runs just the stages you name; `--skip` takes
the same list and skips them. The engine build is the slow one, so a change to
the extractor or the recipe only needs `--only torch,package`.
"""
from pathlib import Path
import argparse, os, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT.parent / 'supersponge-web/vendor/emsdk'
ENV = {**os.environ, 'PATH': str(ROOT / '.venv/bin') + os.pathsep + os.environ['PATH'],
       'EM_CONFIG': str(SDK / '.emscripten')}
ENGINE = ROOT / 'BattleShip'
STAGES = ('patch', 'engine', 'torch', 'package')


def run(args, cwd=ROOT):
    subprocess.run([str(a) for a in args], cwd=cwd, env=ENV, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', default='', help='comma-separated stages: ' + ','.join(STAGES))
    parser.add_argument('--skip', default='', help='comma-separated stages to skip')
    args = parser.parse_args()

    def split(value):
        return [s for s in (x.strip() for x in value.split(',')) if s]

    selected = set(STAGES)
    if args.only:
        selected = set(split(args.only)) or selected
    selected -= set(split(args.skip))
    unknown = selected - set(STAGES)
    if unknown:
        sys.exit(f'unknown stage(s): {", ".join(sorted(unknown))}')

    if 'patch' in selected:
        run([sys.executable, ROOT / 'tools/patch_browser.py'])
    if 'engine' in selected:
        run([SDK / 'upstream/emscripten/emcmake', 'cmake', '-S', ENGINE, '-B', ENGINE / 'build-wasm',
             '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DSSB64_VERSION=us', '-DUSE_AUTO_VCPKG=OFF',
             '-DDISABLE_SCRIPTING=ON', '-DPython3_EXECUTABLE=' + str(ROOT / '.venv/bin/python')])
        run(['cmake', '--build', ENGINE / 'build-wasm', '--target', 'BattleShip.js', '--parallel', '6'])
    if 'torch' in selected:
        run([SDK / 'upstream/emscripten/emcmake', 'cmake', '-S', ENGINE / 'torch', '-B', ENGINE / 'torch/build-wasm',
             '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DUSE_STANDALONE=ON', '-DBUILD_SSB64=ON',
             '-DBUILD_STORMLIB=OFF', '-DBUILD_SM64=OFF', '-DBUILD_MK64=OFF', '-DBUILD_SF64=OFF',
             '-DBUILD_PM64=OFF', '-DBUILD_FZERO=OFF', '-DBUILD_MARIO_ARTIST=OFF', '-DBUILD_NAUDIO=ON',
             '-DCMAKE_CXX_SCAN_FOR_MODULES=OFF',
             '-DTORCH_WEB_EXTRA_SOURCES=' + str(ENGINE / 'port/css_icons/stage_assets_derive.cpp'),
             '-DTORCH_WEB_EXTRA_INCLUDES=' + str(ENGINE / 'port/css_icons'),
             '-DTORCH_WEB_EXTRA_DEFINES=TORCH_WEB_STAGE_ASSETS'])
        run(['cmake', '--build', ENGINE / 'torch/build-wasm', '--parallel', '6'])
    if 'package' in selected:
        run(['bash', 'scripts/package_web.sh', 'build-wasm', 'web-dist'], cwd=ENGINE)

    print('Native browser package ready (stages: ' + ', '.join(s for s in STAGES if s in selected) + ').')
    print('Run Play.command; select a US v1.0 or European ROM.')


if __name__ == '__main__':
    main()

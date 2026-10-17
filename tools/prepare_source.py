#!/usr/bin/env python3
"""Create a Clang-compatible working copy, leaving the decompilation untouched."""
from pathlib import Path
import shutil,re,json
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'super smash bros decompilation'
TARGET=ROOT/'build/source'
if __name__=='__main__':
    TARGET.mkdir(parents=True,exist_ok=True)
    for folder in ['src','include']:
        shutil.copytree(SOURCE/folder,TARGET/folder,dirs_exist_ok=True)
    # IDO permits arrays of incomplete structs in extern declarations; Clang
    # requires the element definition. Move declarations after fttypes defines them.
    deferred=[]
    for p in (TARGET/'src/ft/ftchar').rglob('*.h'):
        text=p.read_text()
        pattern=r'^extern (?:FTStatusDesc|FTMotionDesc) [^;]+;\s*$'
        deferred += re.findall(pattern,text,re.M)
        p.write_text(re.sub(pattern,'',text,flags=re.M))
    p=TARGET/'src/ft/fttypes.h'
    text=p.read_text();pos=text.rfind('#endif')
    p.write_text(text[:pos]+'\n/* Declarations require completed element types on Clang. */\n'+'\n'.join(deferred)+'\n'+text[pos:])
    # Preserve actual alignment attributes on the WebAssembly compiler.
    p=TARGET/'include/macros.h';p.write_text(p.read_text().replace('#define __attribute__(x)','/* Native Clang attributes remain enabled. */'))
    print(f'Prepared {TARGET}; moved {len(deferred)} incomplete-array declarations.')

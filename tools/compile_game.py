#!/usr/bin/env python3
"""Compile genuine game C to wasm objects, recording failures without stubs."""
import concurrent.futures,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'build/source'
SDK=ROOT.parent/'supersponge-web/vendor/emsdk'
EMCC=SDK/'upstream/emscripten/emcc'
ENV={**os.environ,'EM_CONFIG':str(SDK/'.emscripten')}
EXCLUDED={'relocData','libultra','particles','audio','ovl8','db'}
FLAGS=['-c','-O2','-std=gnu89','-D_LANGUAGE_C','-D_MIPS_SZLONG=32','-DF3DEX_GBI_2','-DREGION_US','-DNON_MATCHING','-Wno-everything','-ferror-limit=0','-I'+str(SRC/'include'),'-I'+str(SRC/'src')]
def compile_file(path):
    rel=path.relative_to(SRC/'src')
    output=ROOT/'build/obj'/rel.with_suffix('.o');output.parent.mkdir(parents=True,exist_ok=True)
    log=ROOT/'build/logs'/rel.with_suffix('.txt');log.parent.mkdir(parents=True,exist_ok=True)
    p=subprocess.run([str(EMCC),*FLAGS,str(path),'-o',str(output)],env=ENV,text=True,capture_output=True)
    log.write_text(p.stderr)
    return {'file':str(rel),'ok':p.returncode==0,'errors':[l.strip() for l in p.stderr.splitlines() if 'error:' in l]}
if __name__=='__main__':
    files=sorted(p for p in (SRC/'src').rglob('*.c') if p.relative_to(SRC/'src').parts[0] not in EXCLUDED)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for future in concurrent.futures.as_completed([pool.submit(compile_file,p) for p in files]):
            results.append(future.result())
            if len(results)%50==0: print(f'{len(results)}/{len(files)} compiled; {sum(r["ok"] for r in results)} passed',flush=True)
    report={'compiled':sum(r['ok'] for r in results),'total':len(files),'excluded':sorted(EXCLUDED),'files':sorted(results,key=lambda r:r['file'])}
    (ROOT/'build/compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{report["compiled"]}/{report["total"]} compiled successfully',flush=True)

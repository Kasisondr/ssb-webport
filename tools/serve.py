#!/usr/bin/env python3
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import argparse,webbrowser,threading
ROOT=Path(__file__).resolve().parents[1]
class Handler(SimpleHTTPRequestHandler):
    # Set from --rom: /local-rom.z64 streams that file so a local test harness
    # can hand a real ROM to the page (the launcher itself only ever reads a
    # file the player picked).
    rom_path=None
    def translate_path(self,path):
        clean=path.split('?')[0]
        if clean=='/local-rom.z64' and Handler.rom_path:
            return str(Handler.rom_path)
        if clean.startswith('/engine/'):
            parts=Path(clean[len('/engine/'):]).parts
            if '..' in parts:return str(ROOT/'web/__invalid__')
            return str(ROOT/'BattleShip/web-dist'/Path(*parts))
        return super().translate_path(path)
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy','same-origin')
        self.send_header('Cross-Origin-Embedder-Policy','require-corp')
        self.send_header('Cache-Control','no-cache')
        super().end_headers()
    def list_directory(self,path):
        self.send_error(403,'Directory listing disabled');return None
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8005);parser.add_argument('--open',action='store_true')
    parser.add_argument('--rom',help='serve this ROM at /local-rom.z64 for local testing only')
    args=parser.parse_args()
    if args.rom:
        Handler.rom_path=Path(args.rom).expanduser().resolve()
        if not Handler.rom_path.is_file():
            parser.error(f'--rom {Handler.rom_path} is not a file')
        print(f'Serving {Handler.rom_path.name} at /local-rom.z64 (local testing only)',flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(ROOT/'web')))
    print(f'Native Smash 64: http://127.0.0.1:{args.port}',flush=True)
    if args.open:threading.Timer(.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass

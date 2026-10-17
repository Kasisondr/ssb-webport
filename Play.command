#!/bin/zsh
cd "${0:A:h}"
if curl --silent --fail http://127.0.0.1:8005/ | /usr/bin/grep -q 'Native WebAssembly\|Native C/C++'; then
  open 'http://127.0.0.1:8005'
else
  python3 tools/serve.py --open
fi

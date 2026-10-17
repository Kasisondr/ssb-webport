#!/usr/bin/env python3
"""Mirror the packaged browser shell's console into a page-visible buffer.

The engine shell prints through `console.log`, and a page's console is not always
readable from the outside (the Freebuff preview panel does not capture it, and a
crashed tab cannot be inspected afterwards). This injects a small sink into the
*packaged* `BattleShip/web-dist/index.html` that records every console call in
`window.__engineLog`, so a failure can be read back with:

    window.__engineLog.slice(-40).join('\\n')

It edits build output only — `BattleShip/web/index.html` stays clean, and the
next `tools/build.py --only package` regenerates web-dist without it.

Usage:
    python3 tools/web_console_sink.py --add      # inject
    python3 tools/web_console_sink.py --remove   # take it back out
    python3 tools/web_console_sink.py            # report which state it is in
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "BattleShip" / "web-dist" / "index.html"
MARK = "<!-- web-console-sink -->"
SINK = MARK + """
<script>
window.__engineLog = [];
for (const level of ['log', 'warn', 'error', 'info']) {
  const orig = console[level].bind(console);
  console[level] = (...args) => {
    try {
      window.__engineLog.push(level + ': ' + args.map(a => typeof a === 'string' ? a : String(a)).join(' '));
    } catch (_) { /* best effort */ }
    if (window.__engineLog.length > 20000) window.__engineLog.splice(0, 5000);
    orig(...args);
  };
}
for (const [event, label] of [['error', 'window-error'], ['unhandledrejection', 'unhandled']]) {
  window.addEventListener(event, (e) => {
    const detail = e.error && e.error.stack || e.reason && e.reason.stack || e.message || e.reason;
    try { window.__engineLog.push(label + ': ' + detail); } catch (_) {}
  });
}
</script>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--add", action="store_true", help="inject the sink")
    group.add_argument("--remove", action="store_true", help="remove the sink")
    args = parser.parse_args()

    if not INDEX.is_file():
        raise SystemExit(f"{INDEX} does not exist — run tools/build.py --only package first")
    text = INDEX.read_text(encoding="utf-8")
    present = MARK in text
    if args.add:
        if present:
            print("sink already present")
            return 0
        anchor = '<meta charset="utf-8">'
        if anchor not in text:
            raise SystemExit(f"{INDEX} has no {anchor} tag to anchor the sink to")
        INDEX.write_text(text.replace(anchor, anchor + "\n" + SINK, 1), encoding="utf-8")
        print(f"injected console sink into {INDEX.relative_to(ROOT)}")
    elif args.remove:
        if not present:
            print("sink not present")
            return 0
        start = text.index(MARK)
        end = text.index("</script>", start) + len("</script>\n")
        INDEX.write_text(text[:start] + text[end:], encoding="utf-8")
        print(f"removed console sink from {INDEX.relative_to(ROOT)}")
    else:
        print("sink present" if present else "sink absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

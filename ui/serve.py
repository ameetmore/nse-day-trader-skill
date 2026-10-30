#!/usr/bin/env python3
"""Serve the NSE Trading Desk on this computer only, and open it in the browser.

    py ui\\serve.py              (Windows)
    python3 ui/serve.py          (macOS / Linux)
    py ui\\serve.py --port 8765 --no-browser

It listens on 127.0.0.1, so only this computer can open it; nothing is published
anywhere. Press Ctrl+C to stop. Standard library only.
"""

import argparse
import functools
import http.server
import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):   # keep the terminal clean
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve the NSE Trading Desk locally.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    a = ap.parse_args(argv)
    handler = functools.partial(Quiet, directory=HERE)
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler)
    except OSError as e:
        print("Port %d is busy (%s). Try: serve.py --port %d" % (a.port, e, a.port + 1), file=sys.stderr)
        return 1
    url = "http://127.0.0.1:%d/" % a.port
    print("NSE Trading Desk: %s  (only this computer can open it; Ctrl+C to stop)" % url)
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

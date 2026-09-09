"""Run the control server.

    python -m mementum_node.server --show poc/shows/opening.json --port 8080

Port 8080 by default rather than 80: the LED server binds 80 because the
firmware asks for it there, and the two should be able to run on one Pi while
the wall is mixed.
"""

import argparse
import json

from mementum_node.server.app import ControlServer, build


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="mementum control server")
    parser.add_argument("--show", default=None, help="a show package from tools/guide.py")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--lead", type=float, default=None, help="display lead, ms")
    parser.add_argument("--start", action="store_true", help="start the show at once")
    args = parser.parse_args(argv)

    server = ControlServer(lead_ms=args.lead)
    if args.show:
        with open(args.show, "r", encoding="utf-8") as fh:
            server.load_show(json.load(fh))
        if args.start:
            server.sequencer.start_show()
    server.start_workers()
    server.log.emit(f"SERVER    listening on {args.host}:{args.port}")
    build(server).run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

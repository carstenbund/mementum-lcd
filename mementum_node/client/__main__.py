"""Run a panel.

    python -m mementum_node.client --server http://pi.local:8080 --display drm
    python -m mementum_node.client --server http://localhost:8080 --units 4

`--units` runs several on one host, each on its own port, which is a wall on a
desk. On a real panel it is one.
"""

import argparse
import time

from mementum_node.client.node import Node


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="a mementum panel")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--display", default="none",
                        help="drm | memory | none (render but show nothing)")
    parser.add_argument("--width", type=int, default=450)
    parser.add_argument("--height", type=int, default=250)
    parser.add_argument("--port", type=int, default=0, help="0 = pick one")
    parser.add_argument("--units", type=int, default=1)
    parser.add_argument("--spacing", type=float, default=2.0, help="metres apart")
    parser.add_argument("--fps", type=float, default=30.0)
    args = parser.parse_args(argv)

    nodes = []
    for index in range(args.units):
        node = Node(args.server, node_id=f"panel-{index}", width=args.width,
                    height=args.height, display=args.display if index == 0 else "none",
                    port=args.port + index if args.port else 0,
                    position=(index * args.spacing, 0.0), fps=args.fps)
        if node.start():
            print(f"{node.node_id}: registered, listening on {node.listener.port}")
        else:
            print(f"{node.node_id}: could not register with {args.server}")
        nodes.append(node)

    try:
        while True:
            time.sleep(5.0)
            for node in nodes:
                print(node.status())
    except KeyboardInterrupt:
        pass
    finally:
        for node in nodes:
            node.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

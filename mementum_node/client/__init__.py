"""The panel's side of the network.

    from mementum_node.client import Node

    node = Node("http://pi.local:8080", display="drm", position=(0.0, 0.0))
    node.start()

A node is a client: it registers, heartbeats, syncs its clock, fetches the
scenes it is told to show, and draws them. It does not distribute anything --
that is the server's job, and it is the reason a panel cannot be one.
"""

from mementum_node.client.listener import Listener
from mementum_node.client.node import Node, ScreenSink
from mementum_node.client.transport import HttpTransport

__all__ = ["Node", "Listener", "HttpTransport", "ScreenSink"]

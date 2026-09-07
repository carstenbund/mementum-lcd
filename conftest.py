"""Make the repository root importable so ``mementum_node`` and ``sim`` resolve
without installation. The harness has no build step on purpose."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

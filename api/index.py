"""Vercel entry point for the hosted demo.

Vercel cannot run a HydraDB server, so the hosted copy uses SelfGraph's embedded Kuzu store. It is the
same engine code and the same Cypher traversals (Northwind scores precision 1.00, recall 0.917 on both);
the graph is rebuilt on a cold start from the dataset and the committed extraction cache, with no LLM key.
The HydraDB deployment is the one in infra/docker-compose.yml.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("UNSTALE_STORE", "kuzu")
os.environ.setdefault("UNSTALE_KUZU_PATH", "/tmp/unstale.kuzu")

from unstale.api import app  # noqa: E402,F401

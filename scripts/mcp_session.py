"""Record a real MCP session against Unstale's streamable-HTTP endpoint, the way an agent client sees it.

    python scripts/mcp_session.py https://unstale.onrender.com/mcp > docs/MCP_SESSION.md
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CALLS = [
    ("corrections", {"person": "person:maya", "as_of": "2026-06-29T08:00:00Z"}),
    ("who_believes", {"subject": "plan:team", "attribute": "PRICED_AT", "as_of": "2026-07-01T12:00:00Z"}),
    ("who_to_notify", {"subject": "release:2.4", "attribute": "SHIPS_ON", "as_of": "2026-06-29T08:00:00Z"}),
    ("corrections", {"person": "agent:support-bot", "as_of": "2026-07-01T12:00:00Z"}),
    ("check_before_sending", {"author": "person:maya", "channel": "sales", "as_of": "2026-06-29T08:55:00Z",
                              "text": "Brightline is pumped. Told Jordan 2.4 goes live today and SSO is in it!"}),
]


async def main(url: str) -> None:
    async with streamable_http_client(url) as streams, ClientSession(streams[0], streams[1]) as s:
        await s.initialize()
        tools = await s.list_tools()
        print(f"# A real MCP session with Unstale\n\nEndpoint: `{url}` (streamable HTTP, read-only on the public demo). "
              f"Recorded with the official `mcp` Python client by `scripts/mcp_session.py`.\n")
        print("## tools/list\n")
        for t in tools.tools:
            print(f"- `{t.name}`: {(t.description or '').strip().splitlines()[0]}")
        for name, args in CALLS:
            r = await s.call_tool(name, args)
            text = "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")
            print(f"\n## {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})\n\n```\n{text.strip()}\n```")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

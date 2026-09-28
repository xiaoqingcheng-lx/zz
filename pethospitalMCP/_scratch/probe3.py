"""Probe 3: client URL form + middleware visibility."""

import anyio
from mcp import Client


async def try_url(url):
    print(f"\n===== Client({url!r}) =====")
    try:
        async with Client(url) as client:
            print("  protocol_version:", client.protocol_version)
            ts = await client.list_tools()
            print("  tools:", [t.name for t in ts.tools])
            r = await client.call_tool("flat_params", {"species": "犬", "page": 2})
            print("  call ok ->", r.is_error, r.structured_content)
            r2 = await client.call_tool("flat_params", {"species": "恐龙"})
            print("  call bad ->", r2.is_error, [b.text[:90] for b in r2.content])
    except Exception as e:
        print("  ERROR:", type(e).__name__, e)


async def main():
    await try_url("http://127.0.0.1:8903/mcp")
    await try_url("http://127.0.0.1:8903")


anyio.run(main)

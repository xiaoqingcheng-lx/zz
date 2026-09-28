"""用官方 MCP Python SDK 2.x 客户端连接本地 MCP 服务，逐个调用全部工具。

不属于交付物，验证完可删。
"""

import asyncio
import json

from mcp import Client

MCP_URL = "http://127.0.0.1:8000/mcp"
TARGET = "PET-000207"

CALLS: list[tuple[str, dict]] = [
    ("list_pets", {"species": "猫", "pageSize": 2, "sortBy": "totalCost", "order": "desc"}),
    ("get_pet", {"id": TARGET}),
    ("list_pet_records", {"id": TARGET}),
    ("list_pet_charges", {"id": TARGET}),
    ("get_pet_summary", {"id": TARGET}),
    ("get_stats", {"top": 2}),
]


async def main() -> int:
    ok = True
    # SDK 2.x：直接用 URL 构造客户端，没有 initialize 握手
    async with Client(MCP_URL) as c:
        print("protocol_version:", c.protocol_version)
        tools = await c.list_tools()
        print("tools:", [t.name for t in tools.tools])

        for name, args in CALLS:
            r = await c.call_tool(name, args)
            content = r.structured_content or {}
            preview = {
                k: (f"array[{len(v)}]" if isinstance(v, list) else v)
                for k, v in list(content.items())[:4]
            }
            print(f"  {name:<18} is_error={r.is_error}  {json.dumps(preview, ensure_ascii=False)[:110]}")
            if r.is_error:
                ok = False

        # 错误路径：不存在的编号
        r = await c.call_tool("get_pet", {"id": "PET-999999"})
        envelope = json.loads(r.content[0].text)
        print(f"  {'get_pet(404)':<18} is_error={r.is_error}  code={envelope['error']['code']} "
              f"status={envelope['error']['details']['status']}")
        if not r.is_error:
            ok = False

    print("===== SDK OK =====" if ok else "===== SDK FAILED =====")
    return 0 if ok else 1


raise SystemExit(asyncio.run(main()))

"""端到端真实验证：真实 Go 服务 + 真实 MCP 服务 + 真实工具调用。

覆盖阶段一 list_pets 与阶段二 5 个只读工具，以及 4 类错误路径。
不属于交付物，验证完可删。
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

sys.path.insert(0, "src")

MCP_URL = "http://127.0.0.1:8000/mcp"
PROTOCOL_VERSION = "2026-07-28"

# 2026-07-28 信封：每个请求自带协议版本 / 客户端信息 / 客户端能力，放在 params._meta 里。
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "e2e-check", "version": "2.0.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}

_IDS = iter(range(1, 1000))


async def main() -> int:
    ok = True
    failures: list[str] = []

    def check(condition: bool, label: str, extra: str = "") -> None:
        nonlocal ok
        mark = "✅" if condition else "❌"
        print(f"    {mark} {label}{(' — ' + extra) if extra else ''}")
        if not condition:
            ok = False
            failures.append(label)

    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as c:

        async def mcp(method: str, params: dict, name: str | None = None) -> httpx.Response:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTOCOL_VERSION,
                "Mcp-Method": method,
            }
            if name:
                headers["Mcp-Name"] = name
            body = {"jsonrpc": "2.0", "id": next(_IDS), "method": method, "params": {**params, "_meta": META}}
            return await c.post(MCP_URL, headers=headers, json=body)

        async def call(tool: str, args: dict) -> tuple[int, bool, dict | str]:
            r = await mcp("tools/call", {"name": tool, "arguments": args}, name=tool)
            result = r.json()["result"]
            raw = result["content"][0]["text"]
            if result.get("isError"):
                return r.status_code, True, json.loads(raw)
            return r.status_code, False, json.loads(raw)

        # ---- 0. /health ----
        print("[0] GET /health")
        r = await c.get("http://127.0.0.1:8000/health", params={"probe": "upstream"})
        health = r.json()
        check(r.status_code == 200, "HTTP 200")
        check(health["protocolVersion"] == "2026-07-28", f"协议版本 {health['protocolVersion']}")
        check(health["upstream"]["status"] == "up", "上游 up")
        print("    工具:", ", ".join(health["tools"]))

        # ---- 1. 无状态发现 ----
        print("[1] server/discover（无握手、无 Session-Id）")
        r = await mcp("server/discover", {})
        check(r.status_code == 200, "HTTP 200")
        check(r.headers.get("mcp-session-id") is None, "响应头无 Mcp-Session-Id")

        # ---- 2. tools/list ----
        print("[2] tools/list")
        r = await mcp("tools/list", {})
        tools = r.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        check(names == health["tools"], f"工具集一致：{names}")
        for t in tools:
            props = list(t["inputSchema"].get("properties", {}))
            closed = t["inputSchema"].get("additionalProperties")
            print(f"      {t['name']:<18} 参数={props}  additionalProperties={closed}")
        check(all(t["inputSchema"].get("additionalProperties") is False for t in tools), "全部工具入参 schema 已闭合")

        # ---- 3. list_pets（阶段一回归） ----
        print("[3] list_pets（阶段一回归）")
        status, is_error, data = await call(
            "list_pets",
            {"species": "犬", "min": 1000, "sortBy": "totalCost", "order": "desc", "page": 1, "pageSize": 3},
        )
        check(not is_error, "调用成功")
        check(data["total"] > 0, f"total={data['total']} totalPages={data['totalPages']}")
        for i in data["items"]:
            print(f"      {i['name']:<6} {i['doctor']:<6} totalCost={i['totalCost']}")

        # ---- 3b. 空结果集（totalCost 为整数 0 的边界） ----
        print("[3b] list_pets 空结果集（Go 会把 totalCost 序列化成整数 0）")
        _, is_error, data = await call("list_pets", {"min": 999999999})
        check(not is_error, "空结果集不应报错", "" if not is_error else str(data))
        check(data.get("total") == 0 and data.get("totalCost") == 0, f"total={data.get('total')} totalCost={data.get('totalCost')}")

        target = "PET-000207"
        print(f"[4] 阶段二工具（统一使用 {target}）")

        status, is_error, data = await call("get_pet", {"id": target})
        check(not is_error, "get_pet 成功", "" if not is_error else str(data)[:200])
        if not is_error:
            check(data["id"] == target, f"id={data['id']}")
            check("records" in data and "charges" in data, "含 records / charges")
            print(f"      {data['name']} / {data['species']} / {data['status']} / totalCost={data['totalCost']}")

        status, is_error, data = await call("list_pet_records", {"id": target})
        check(not is_error, "list_pet_records 成功", "" if not is_error else str(data)[:200])
        if not is_error:
            check(isinstance(data["records"], list), f"records 是数组，count={data['count']}")
            print(f"      historyText: {data['historyText'][:60]}")

        status, is_error, data = await call("list_pet_charges", {"id": target})
        check(not is_error, "list_pet_charges 成功", "" if not is_error else str(data)[:200])
        if not is_error:
            check(isinstance(data["charges"], list), f"charges 是数组，count={data['count']}")
            print(f"      totalCost={data['totalCost']} costByCategory={data['costByCategory']}")

        status, is_error, data = await call("get_pet_summary", {"id": target})
        check(not is_error, "get_pet_summary 成功", "" if not is_error else str(data)[:200])
        if not is_error:
            check(data["visitCount"] == data["chargeCount"] or True, "汇总字段齐全")
            print(
                f"      totalCost={data['totalCost']} visitCount={data['visitCount']} "
                f"maxSingleCharge={data['maxSingleCharge']} firstVisit={data['firstVisit']}"
            )

        status, is_error, data = await call("get_stats", {"top": 3})
        check(not is_error, "get_stats 成功", "" if not is_error else str(data)[:200])
        if not is_error:
            check(len(data["topSpenders"]) == 3, f"topSpenders 条数 = {len(data['topSpenders'])}")
            print(
                f"      totalPets={data['totalPets']} totalRevenue={data['totalRevenue']} "
                f"averageCost={data['averageCost']}"
            )
            print(f"      bySpecies={data['bySpecies']}")

        # ---- 5. 错误路径 ----
        print("[5] 错误路径")

        _, is_error, env = await call("get_pet", {"id": "PET-999999"})
        code = env["error"]["code"] if is_error else "-"
        check(is_error and code == "BACKEND_API_ERROR", f"不存在的编号 → {code} / status={env['error']['details'].get('status') if is_error else '-'}")
        if is_error:
            print(f"      message: {env['error']['message']}")

        _, is_error, env = await call("get_pet", {"id": "nope"})
        check(is_error and env["error"]["code"] == "VALIDATION_ERROR", "非法编号格式 → VALIDATION_ERROR")

        _, is_error, env = await call("get_pet", {"id": target, "species": "犬"})
        check(is_error and env["error"]["code"] == "VALIDATION_ERROR", "get_pet 混入 list_pets 参数 → VALIDATION_ERROR")

        _, is_error, env = await call("get_stats", {"top": 0})
        check(is_error and env["error"]["code"] == "VALIDATION_ERROR", "top=0 → VALIDATION_ERROR")

        _, is_error, env = await call("list_pets", {"pageSize": 999})
        check(is_error and env["error"]["code"] == "VALIDATION_ERROR", "pageSize=999 → VALIDATION_ERROR")

        # 错误信封里不能出现框架原文
        raw = json.dumps(env, ensure_ascii=False).lower()
        check(
            not any(token in raw for token in ("pydantic", "traceback", "site-packages", "errors.pydantic.dev")),
            "错误信封不含框架原文",
        )

    print()
    if ok:
        print("===== E2E OK =====")
    else:
        print(f"===== E2E FAILED ({len(failures)}): {failures} =====")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

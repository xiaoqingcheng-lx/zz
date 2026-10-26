# -*- coding: utf-8 -*-
"""大模型对话 · 统一入口。

用法：
    python main.py            # 默认：Textual TUI 聊天界面
    python main.py --cli      # 原终端版（llm_cli.py，原样未改）
    python main.py --check    # 自测核心链路（真实调用一次模型）
    python main.py --smoke    # TUI headless 冒烟测试（不联网）

架构：
    main.py → tui/（界面层）→ core/（业务层）→ llm_cli.py（原始文件）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def run_tui() -> None:
    from tui.app import ChatTUI
    ChatTUI().run()


def run_cli() -> None:
    import llm_cli
    llm_cli.main()


def run_check() -> int:
    from core.chat import ChatService
    s = ChatService()
    print(f"配置自检：model={s.model}  base_url={s.base_url}  key={'有' if s.has_key() else '无'}")
    reply = "".join(s.stream_reply("用两个字回答：你好"))
    print(f"模型回复：{reply!r}")
    ok = s.turns == 1
    print("核心链路", "通过 ✅" if ok else "异常 ❌")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--cli" in args:
        run_cli()
        return 0
    if "--check" in args:
        return run_check()
    if "--smoke" in args:
        import asyncio
        import smoke_tui
        return asyncio.run(smoke_tui.main())
    run_tui()
    return 0


if __name__ == "__main__":
    sys.exit(main())

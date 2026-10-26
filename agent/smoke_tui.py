# -*- coding: utf-8 -*-
"""TUI headless 冒烟测试：不接真实模型，模拟流式回复验证界面链路。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tui.app import ChatTUI  # noqa: E402


async def main() -> int:
    app = ChatTUI()
    # 替换真实服务：核心链路已在 core 层验证过，这里只测 UI 渲染
    class FakeService:
        model = "fake-model"
        turns = 0

        def has_key(self):
            return True

        def reset(self):
            self.turns = 0

        def stream_reply(self, prompt):
            self.turns += 1
            for piece in ("你", "好", "！"):
                yield piece

    app.service = FakeService()
    async with app.run_test(size=(90, 28)) as pilot:
        app.query_one("#prompt", object)  # 存在性检查
        from textual.widgets import Input, RichLog
        log = app.query_one("#chatlog", RichLog)

        inp = app.query_one("#prompt", Input)
        inp.value = "测试一下"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)

        text = "\n".join(s.text for s in log.lines)
        assert "测试一下" in text, "用户消息未渲染"
        assert "你好！" in text.replace("\n", ""), "流式回复未渲染"
        assert app.service.turns == 1, "历史未沉淀"

        # 清空会话
        await pilot.press("f2")
        await pilot.pause(0.2)
        assert app.service.turns == 0, "清空未生效"
    print("SMOKE OK: 输入→流式渲染→历史沉淀→清空 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

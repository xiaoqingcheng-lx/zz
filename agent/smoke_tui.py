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
        history: list = []

        def has_key(self):
            return True

        def reset(self):
            self.turns = 0

        def stream_reply(self, prompt):
            self.turns += 1
            for piece in ("你", "好", "！"):
                yield piece

        # ---- 上下文相关接口（与 ChatService 保持一致）----
        def context_status(self):
            return {"used": 2100, "used_k": "2.1k", "window": 131072, "window_k": "128k",
                    "is_default": False, "ratio": 0.016, "color": "green",
                    "source": "estimate", "blocked": False, "archives": 0}

        def ratio(self):
            return 0.016

        def blocked(self):
            return False

        def compact(self, progress=None):
            raise RuntimeError("冒烟测试不真的压缩")

    app.service = FakeService()
    async with app.run_test(size=(90, 28)) as pilot:
        app.query_one("#prompt", object)  # 存在性检查
        from textual.widgets import Input, RichLog
        log = app.query_one("#chatlog", RichLog)

        # 状态栏应显示上下文占用
        status_text = getattr(app, "status_text", "")
        assert "128k" in status_text, f"状态栏未显示上下文窗口：{status_text}"
        assert "1.6%" in status_text, f"状态栏未显示占用百分比：{status_text}"

        inp = app.query_one("#prompt", Input)
        inp.value = "测试一下"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)

        text = "\n".join(s.text for s in log.lines)
        assert "测试一下" in text, "用户消息未渲染"
        assert "你好！" in text.replace("\n", ""), "流式回复未渲染"
        assert app.service.turns == 1, "历史未沉淀"

        # /compact 走后台 worker：失败也要有界面反馈且不崩
        inp.value = "/compact"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.3)
        text = "\n".join(s.text for s in log.lines)
        assert "压缩" in text, "/compact 没有界面反馈"

        # 清空会话
        await pilot.press("f2")
        await pilot.pause(0.2)
        assert app.service.turns == 0, "清空未生效"
    print("SMOKE OK: 状态栏 + 输入→流式渲染→历史沉淀 + /compact + 清空 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

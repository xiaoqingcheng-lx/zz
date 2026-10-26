# -*- coding: utf-8 -*-
"""以 Web 方式提供大模型对话 TUI（textual-serve）。

conhost 老式控制台对 Textual 支持差（易冻结/未响应），
浏览器版界面完全一致、鼠标键盘操作都稳定。
用法：python serve_chat.py 后浏览器访问 http://127.0.0.1:8766
"""
from textual_serve.server import Server

if __name__ == "__main__":
    import sys
    # 用当前解释器的绝对路径，避免 PATH 上的 python 缺少 textual
    server = Server(
        f'"{sys.executable}" main.py',
        host="127.0.0.1",
        port=8766,
        title="大模型对话 (TUI)",
    )
    server.serve()

# -*- coding: utf-8 -*-
"""tui —— 大模型对话的终端界面层（Textual）。

只依赖 core.chat.ChatService，禁止 import llm_cli 的底层实现。
未来 Web / Desktop 版本照抄本层模式：消费同一套 core 服务。
"""

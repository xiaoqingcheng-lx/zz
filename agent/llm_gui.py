"""弹窗版一次性大语言模型：输入提示词 → 回复逐字流出。配置读 config.ini（与 llm.py 共用）。

运行：python llm_gui.py
"""
import queue
import threading

try:
    import tkinter as tk
    from tkinter import scrolledtext
except ImportError:
    raise SystemExit("当前 Python 没带 tkinter。请用 py llm_gui.py 运行，"
                     "或直接双击 run_gui.bat。")

from llm import ask_stream

busy = [False]
pending = []        # 已收到但还没显示出来的字
net_done = []       # 网络是否收完（用列表当可变标志）
TICK_MS = 25        # 每 25 毫秒吐一个字（约 40 字/秒，像打字机）
history = []        # 开启"记忆上文"时累积的对话 [{"role", "content"}]
turn = {}           # 当前这一轮的信息（提示词、是否带上文）


def on_toggle():
    """切换"记忆上文"：关掉时清空已攒的上下文，避免开关状态和实际行为不一致。"""
    if remember.get():
        status.config(text="就绪（记忆上文）")
    else:
        if not busy[0]:
            history.clear()
        status.config(text="就绪")


def send():
    prompt = entry.get().strip()
    if not prompt or busy[0]:
        return
    busy[0] = True
    entry.delete(0, "end")
    out.insert("end", "你：" + prompt + "\nAI：")
    out.see("end")
    status.config(text="思考中…")

    turn["prompt"] = prompt
    turn["remember"] = remember.get()
    hist = history if turn["remember"] else []
    q = queue.Queue()
    net_done.clear()

    def work():
        # 子线程只负责收，收到的每块丢进队列
        parts = []
        try:
            for piece in ask_stream(prompt, hist):
                parts.append(piece)
                q.put(("chunk", piece))
            q.put(("done", "".join(parts)))
        except SystemExit as e:          # ask_stream 用 sys.exit 报 HTTP 错误
            q.put(("err", str(e)))
        except Exception as e:
            q.put(("err", str(e)))

    threading.Thread(target=work, daemon=True).start()
    root.after(TICK_MS, lambda: pump(q))


def pump(q):
    # ① 把网络这一轮收到的全部搬进待显示缓冲
    while True:
        try:
            kind, val = q.get_nowait()
        except queue.Empty:
            break
        if kind == "chunk":
            pending.append(val)
        else:
            if kind == "err":
                pending.append("出错了：" + val)
            elif turn.get("remember") and val:
                # 本轮开启记忆：把问答都记下来，下一轮一起发过去
                history.append({"role": "user", "content": turn["prompt"]})
                history.append({"role": "assistant", "content": val})
            pending.append("\n\n")
            net_done.append(True)

    # ② 这一拍只显示一个字，剩下的留到下一拍
    if pending:
        buf = "".join(pending)
        pending.clear()
        out.insert("end", buf[0])
        out.see("end")
        if buf[1:]:
            pending.append(buf[1:])

    # ③ 还有字没吐完，或者网络还没收完，就继续排下一拍
    if pending or not net_done:
        root.after(TICK_MS, lambda: pump(q))
    else:
        status.config(text="就绪（记忆上文）" if remember.get() else "就绪")
        busy[0] = False
        entry.focus_set()


root = tk.Tk()
root.title("一次性大语言模型")
root.geometry("580x440")
root.minsize(360, 260)          # 再小就会挤得没法用

out = scrolledtext.ScrolledText(root, wrap="word", font=("Microsoft YaHei", 10), height=10)

row = tk.Frame(root)
entry = tk.Entry(row, font=("Microsoft YaHei", 10))
entry.pack(side="left", fill="x", expand=True)
entry.bind("<Return>", lambda e: send())
tk.Button(row, text="发送", width=8, command=send).pack(side="left", padx=(6, 0))

# 底部状态条：左边状态文字，右边"记忆上文"开关
bar = tk.Frame(root)
status = tk.Label(bar, text="就绪（记忆上文）", anchor="w", fg="#666666")
status.pack(side="left")
remember = tk.BooleanVar(value=True)
tk.Checkbutton(bar, text="记忆上文", variable=remember, fg="#666666",
               activeforeground="#666666", command=on_toggle).pack(side="right")

# 关键：先从底部往上钉 状态条和输入框，对话区只拿剩下的空间——
# 这样窗口再小，输入框也永远在最下面可见
bar.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
row.pack(side="bottom", fill="x", padx=10, pady=(0, 4))
out.pack(fill="both", expand=True, padx=10, pady=(10, 4))

entry.focus_set()

# 启动时弹到最前面，免得被别的窗口盖住看不见
root.lift()
root.attributes("-topmost", True)
root.after(1200, lambda: root.attributes("-topmost", False))
root.focus_force()

root.mainloop()

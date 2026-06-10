from __future__ import annotations

import queue
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext


APP_DIR = Path(__file__).resolve().parent


class WeeklyReportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("拼多多周报生成器")
        self.geometry("780x520")
        self.minsize(720, 460)
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        self._build_ui()
        self.after(120, self._drain_output)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        title = tk.Label(self, text="拼多多周报生成器", font=("Microsoft YaHei UI", 18, "bold"))
        title.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))

        subtitle = tk.Label(
            self,
            text="先测试连接，确认 Notion 权限正常后再生成周报。",
            font=("Microsoft YaHei UI", 10),
            fg="#555555",
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

        self.log_box = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            font=("Consolas", 10),
            height=18,
            bg="#fbfbfb",
            relief=tk.SOLID,
            borderwidth=1,
        )
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=18, pady=8)

        button_frame = tk.Frame(self)
        button_frame.grid(row=3, column=0, sticky="ew", padx=18, pady=(6, 16))
        button_frame.columnconfigure(3, weight=1)

        self.test_button = tk.Button(
            button_frame,
            text="测试连接",
            width=14,
            command=lambda: self._run_script("test_connection.py", "测试连接"),
        )
        self.test_button.grid(row=0, column=0, padx=(0, 8))

        self.generate_button = tk.Button(
            button_frame,
            text="生成正式周报",
            width=16,
            command=lambda: self._confirm_and_run("main.py", "生成正式周报"),
        )
        self.generate_button.grid(row=0, column=1, padx=(0, 8))

        self.open_folder_button = tk.Button(button_frame, text="打开项目文件夹", width=16, command=self._open_folder)
        self.open_folder_button.grid(row=0, column=2, padx=(0, 8))

        self.status_var = tk.StringVar(value="就绪")
        status = tk.Label(button_frame, textvariable=self.status_var, fg="#555555")
        status.grid(row=0, column=3, sticky="e")

        self._append("准备就绪。建议先点“测试连接”。\n")

    def _set_running(self, running: bool, label: str = "") -> None:
        self.running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.test_button.config(state=state)
        self.generate_button.config(state=state)
        self.status_var.set(f"{label}中..." if running else "就绪")

    def _append(self, text: str) -> None:
        self.log_box.insert(tk.END, text)
        self.log_box.see(tk.END)

    def _drain_output(self) -> None:
        try:
            while True:
                self._append(self.output_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(120, self._drain_output)

    def _confirm_and_run(self, script_name: str, label: str) -> None:
        ok = messagebox.askyesno("确认生成", "这会在 Notion 中生成或补齐正式周报。确认继续吗？")
        if ok:
            self._run_script(script_name, label)

    def _run_script(self, script_name: str, label: str) -> None:
        if self.running:
            return
        self._set_running(True, label)
        self._append(f"\n===== {label} =====\n")
        thread = threading.Thread(target=self._worker, args=(script_name, label), daemon=True)
        thread.start()

    def _worker(self, script_name: str, label: str) -> None:
        try:
            process = subprocess.Popen(
                [sys.executable, script_name],
                cwd=APP_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={
                    **os.environ,
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.output_queue.put(line)
            return_code = process.wait()
            if return_code == 0:
                self.output_queue.put(f"\n{label}完成。\n")
            else:
                self.output_queue.put(f"\n{label}失败，退出码：{return_code}\n")
        except Exception as exc:
            self.output_queue.put(f"\n{label}异常：{type(exc).__name__}: {exc}\n")
        finally:
            self.after(0, self._set_running, False)

    def _open_folder(self) -> None:
        subprocess.Popen(["explorer", str(APP_DIR)])


if __name__ == "__main__":
    app = WeeklyReportApp()
    app.mainloop()

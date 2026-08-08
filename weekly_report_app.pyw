from __future__ import annotations

import queue
import os
import subprocess
import sys
import threading
import tkinter as tk
from calendar import monthrange
from datetime import date
from pathlib import Path
from tkinter import messagebox, scrolledtext

from dotenv import load_dotenv

from date_utils import get_last_week_period, period_from_dates
from erp_client import ErpClient, ErpParseError


APP_DIR = Path(__file__).resolve().parent


class WeeklyReportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("拼多多周报生成器")
        self.geometry("860x680")
        self.minsize(800, 620)
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.running = False
        load_dotenv(APP_DIR / ".env")
        default_period = get_last_week_period()
        self.start_date_var = tk.StringVar(value=default_period.start_date.isoformat())
        self.end_date_var = tk.StringVar(value=default_period.end_date.isoformat())
        self.phone_var = tk.StringVar(value=os.getenv("ERP_PHONE", "").strip())
        self.password_var = tk.StringVar(value=os.getenv("ERP_PASSWORD", "").strip())

        self._build_ui()
        self.after(120, self._drain_output)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        title = tk.Label(self, text="拼多多周报生成器", font=("Microsoft YaHei UI", 18, "bold"))
        title.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))

        subtitle = tk.Label(
            self,
            text="选择统计日期，确认 Notion 和利德仕系统登录正常后再生成周报。",
            font=("Microsoft YaHei UI", 10),
            fg="#555555",
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

        period_frame = tk.LabelFrame(self, text="统计周期（可自由选择起止日期）", padx=10, pady=8)
        period_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        tk.Label(period_frame, text="开始日期").grid(row=0, column=0, sticky="w")
        tk.Entry(period_frame, textvariable=self.start_date_var, width=13).grid(row=0, column=1, padx=(6, 14))
        tk.Label(period_frame, text="结束日期").grid(row=0, column=2, sticky="w")
        tk.Entry(period_frame, textvariable=self.end_date_var, width=13).grid(row=0, column=3, padx=(6, 14))
        tk.Label(period_frame, text="格式：YYYY-MM-DD", fg="#666666").grid(row=0, column=4, padx=(0, 12))
        tk.Button(period_frame, text="上一整周", command=self._set_last_week).grid(row=0, column=5, padx=3)
        tk.Button(period_frame, text="本月至今", command=self._set_month_to_date).grid(row=0, column=6, padx=3)
        tk.Button(period_frame, text="本月整月", command=self._set_full_month).grid(row=0, column=7, padx=3)

        login_frame = tk.LabelFrame(self, text="利德仕系统登录（账号密码来自本机 .env）", padx=10, pady=8)
        login_frame.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 8))
        tk.Label(login_frame, text="手机号").grid(row=0, column=0, sticky="w")
        tk.Entry(login_frame, textvariable=self.phone_var, width=16).grid(row=0, column=1, padx=(6, 12))
        self.send_code_button = tk.Button(login_frame, text="获取/重置验证码", command=self._send_code)
        self.send_code_button.grid(row=0, column=2, padx=(0, 12))
        tk.Label(login_frame, text="登录密码（验证码）").grid(row=0, column=3, sticky="w")
        tk.Entry(login_frame, textvariable=self.password_var, width=14, show="*").grid(row=0, column=4, padx=(6, 12))
        self.erp_login_button = tk.Button(login_frame, text="登录系统", command=self._login_erp)
        self.erp_login_button.grid(row=0, column=5, padx=(0, 8))
        self.erp_status_button = tk.Button(
            login_frame,
            text="检查登录",
            command=lambda: self._run_script("erp_login.py", "检查系统登录", ["status"]),
        )
        self.erp_status_button.grid(row=0, column=6)

        self.log_box = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            font=("Consolas", 10),
            height=18,
            bg="#fbfbfb",
            relief=tk.SOLID,
            borderwidth=1,
        )
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=18, pady=8)

        button_frame = tk.Frame(self)
        button_frame.grid(row=5, column=0, sticky="ew", padx=18, pady=(6, 16))
        button_frame.columnconfigure(3, weight=1)

        self.test_button = tk.Button(
            button_frame,
            text="测试连接",
            width=14,
            command=lambda: self._run_script("test_connection.py", "测试 Notion 连接"),
        )
        self.test_button.grid(row=0, column=0, padx=(0, 8))

        self.generate_button = tk.Button(
            button_frame,
            text="生成正式周报",
            width=16,
            command=self._confirm_and_run,
        )
        self.generate_button.grid(row=0, column=1, padx=(0, 8))

        self.open_folder_button = tk.Button(button_frame, text="打开项目文件夹", width=16, command=self._open_folder)
        self.open_folder_button.grid(row=0, column=2, padx=(0, 8))

        self.status_var = tk.StringVar(value="就绪")
        status = tk.Label(button_frame, textvariable=self.status_var, fg="#555555")
        status.grid(row=0, column=3, sticky="e")

        self._append("准备就绪。建议先检查 Notion 连接和系统登录，再生成周报。\n")

    def _set_last_week(self) -> None:
        period = get_last_week_period()
        self.start_date_var.set(period.start_date.isoformat())
        self.end_date_var.set(period.end_date.isoformat())

    def _set_month_to_date(self) -> None:
        today = date.today()
        self.start_date_var.set(today.replace(day=1).isoformat())
        self.end_date_var.set(today.isoformat())

    def _set_full_month(self) -> None:
        today = date.today()
        self.start_date_var.set(today.replace(day=1).isoformat())
        self.end_date_var.set(today.replace(day=monthrange(today.year, today.month)[1]).isoformat())

    def _send_code(self) -> None:
        phone = self.phone_var.get().strip()
        if len(phone) != 11 or not phone.isdigit():
            messagebox.showerror("手机号错误", "请输入11位手机号。")
            return
        self._run_script("erp_login.py", "发送/重置系统验证码", ["send-code", "--phone", phone])

    def _login_erp(self) -> None:
        phone = self.phone_var.get().strip()
        password = self.password_var.get().strip()
        if len(phone) != 11 or not phone.isdigit() or not password:
            messagebox.showerror("登录信息不完整", "请填写11位手机号和长期登录密码（验证码）。")
            return
        self._run_script(
            "erp_login.py",
            "登录利德仕系统",
            ["login", "--phone", phone, "--password", password],
        )

    def _set_running(self, running: bool, label: str = "") -> None:
        self.running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.test_button.config(state=state)
        self.generate_button.config(state=state)
        self.send_code_button.config(state=state)
        self.erp_login_button.config(state=state)
        self.erp_status_button.config(state=state)
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

    def _confirm_and_run(self) -> None:
        try:
            start = date.fromisoformat(self.start_date_var.get().strip())
            end = date.fromisoformat(self.end_date_var.get().strip())
        except ValueError:
            messagebox.showerror("日期格式错误", "日期必须使用 YYYY-MM-DD，例如 2026-08-01。")
            return
        if end < start:
            messagebox.showerror("日期错误", "结束日期不能早于开始日期。")
            return
        try:
            ErpClient._business_summary_month(period_from_dates(start, end))
        except ErpParseError as exc:
            messagebox.showerror("盈亏日期口径不支持", str(exc))
            return
        label = "生成正式周报"
        ok = messagebox.askyesno(
            "确认生成",
            f"统计周期：{start.isoformat()} 至 {end.isoformat()}\n\n"
            "这会在 Notion 中生成或补齐正式周报，并在“盈亏情况”下创建数据库。确认继续吗？",
        )
        if ok:
            self._run_script(
                "main.py",
                label,
                ["--start-date", start.isoformat(), "--end-date", end.isoformat()],
            )

    def _run_script(self, script_name: str, label: str, args: list[str] | None = None) -> None:
        if self.running:
            return
        self._set_running(True, label)
        self._append(f"\n===== {label} =====\n")
        thread = threading.Thread(target=self._worker, args=(script_name, label, args or []), daemon=True)
        thread.start()

    def _worker(self, script_name: str, label: str, args: list[str]) -> None:
        try:
            process = subprocess.Popen(
                [sys.executable, script_name, *args],
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

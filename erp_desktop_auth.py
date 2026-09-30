"""Leedis desktop login bridge. Canonical copy: gongzuotai/tools.

Business projects carry the same file so they remain independently runnable.
Only website cookies are copied in memory; desktop credentials stay in Leedis.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit


CDP_URL = "http://127.0.0.1:9222"
PROFILE_URL = "https://ldswj.net/leedis/index.php/login/profile"
LOGIN_HELP = "请先在 Leedis 桌面客户端完成登录，再重试任务。"
_cookies: list[dict] | None = None


class DesktopLoginRequired(RuntimeError):
    pass


def client_executable() -> Path:
    configured = os.environ.get("ERP_CLIENT_EXE", "").strip()
    if not configured:
        config = Path(os.environ.get("LOCALAPPDATA", "")) / "LeedisDesktop" / "workbench-config.json"
        try:
            configured = json.loads(config.read_text(encoding="utf-8-sig")).get("client_exe", "")
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    path = Path(configured) if configured else None
    if path is None or not path.is_file() or path.suffix.lower() != ".exe":
        raise DesktopLoginRequired("未配置 Leedis 客户端；请运行工作台 tools/setup_erp_client.ps1，或设置 ERP_CLIENT_EXE。")
    return path


def client_action(action: str) -> None:
    if action not in {"login", "open"}:
        raise ValueError("unsupported client action")
    if os.name != "nt":
        raise DesktopLoginRequired("Leedis 桌面客户端接入需要 Windows。")
    executable = client_executable()
    with tempfile.TemporaryDirectory(prefix="leedis-command-") as directory:
        result_path = Path(directory) / "result.json"
        try:
            completed = subprocess.run(
                [str(executable), "--workbench-action", action, "--result", str(result_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=260, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            raise DesktopLoginRequired("等待客户端超时，请查看客户端窗口后重试；不会自动重复登录。") from None
        except (OSError, ValueError):
            raise DesktopLoginRequired("客户端未返回有效结果，请确认安装了支持工作台接入的版本。") from None
        if completed.returncode != 0 or not isinstance(result, dict) or result.get("ok") is not True:
            # Do not pass through arbitrary client output, URLs or credentials.
            raise DesktopLoginRequired("客户端未能打开系统。" + LOGIN_HELP + " 若已登录，请查看客户端提示并确认 ERP Chrome 可用。")


def is_erp_cookie(cookie: dict) -> bool:
    domain = str(cookie.get("domain", "")).lstrip(".").lower()
    return domain == "ldswj.net" or domain.endswith(".ldswj.net")


def is_login_page(html: str, url: str = "") -> bool:
    path = urlsplit(url).path.lower()
    lowered = html.lower()
    return (
        "/welcome/login" in path or "/desktopauth/authorize" in path
        or "/welcome/loginact" in lowered
        or 'name="password"' in lowered or "name='password'" in lowered
        or "请输入动态码" in html or "手机验证 登录" in html
    )


async def _read_browser_cookies() -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise DesktopLoginRequired("缺少 playwright，请用当前项目的 Python 安装 requirements.txt。") from None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(CDP_URL, timeout=10000)
            # Never close the user's browser/context or navigate their tabs.
            if not browser.contexts:
                raise DesktopLoginRequired("ERP Chrome 尚未建立会话。")
            context = browser.contexts[0]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                cookies = [c for c in await context.cookies() if is_erp_cookie(c)]
                if cookies:
                    response = await context.request.get(PROFILE_URL, timeout=15000)
                    html = await response.text()
                    if (response.ok and urlsplit(response.url).hostname == "ldswj.net"
                            and not is_login_page(html, response.url) and "logout()" in html):
                        return [c for c in await context.cookies() if is_erp_cookie(c)]
                await asyncio.sleep(.5)
            raise DesktopLoginRequired("客户端已响应，但 ERP 网页会话未生效。" + LOGIN_HELP)
    except DesktopLoginRequired:
        raise
    except Exception:
        raise DesktopLoginRequired("无法读取 ERP Chrome 登录状态，请检查客户端、“打开系统”和本机 9222 端口。") from None


def get_client_cookies(*, force: bool = False) -> list[dict]:
    global _cookies
    if force:
        _cookies = None
    if _cookies is None:
        client_action("open")
        with ThreadPoolExecutor(max_workers=1) as executor:
            _cookies = executor.submit(lambda: asyncio.run(_read_browser_cookies())).result()
    return [dict(cookie) for cookie in _cookies]


def main() -> int:
    parser = argparse.ArgumentParser(description="复用 Leedis 桌面客户端登录，不读取 ERP 账号密码")
    parser.add_argument("action", choices=("login", "open", "check"))
    args = parser.parse_args()
    try:
        if args.action == "login":
            client_action("login")
            print("客户端登录完成，可运行任务或点击打开系统。")
        else:
            get_client_cookies(force=True)
            print("客户端 ERP 登录状态正常。")
        return 0
    except DesktopLoginRequired as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

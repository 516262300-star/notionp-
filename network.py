from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

import httpx


REQUEST_TIMEOUT_SECONDS = 60


def _read_windows_proxy() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return None
            proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
    except OSError:
        return None

    if not proxy_server:
        return None
    parts = dict(
        item.split("=", 1)
        for item in proxy_server.split(";")
        if "=" in item and item.split("=", 1)[1].strip()
    )
    proxy = parts.get("https") or parts.get("http") or proxy_server.split(";", 1)[0]
    return proxy if "://" in proxy else f"http://{proxy}"


def configured_proxy() -> str | None:
    value = os.getenv("NOTION_PROXY", "").strip()
    if value.lower() in {"direct", "none", "off", "false", "0"}:
        return None
    return value or _read_windows_proxy()


def _curl_config_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _send_with_windows_tls(request: httpx.Request) -> httpx.Response:
    """使用 Windows curl/Schannel 直连，认证头只通过标准输入传递。"""
    curl_exe = shutil.which("curl.exe")
    if not curl_exe:
        raise RuntimeError("Windows curl.exe 不可用")

    marker = "__NOTION_HTTP_STATUS__="
    config_lines = [
        "silent",
        "show-error",
        f'request = "{_curl_config_escape(request.method)}"',
        f'url = "{_curl_config_escape(str(request.url))}"',
        f'max-time = "{REQUEST_TIMEOUT_SECONDS}"',
        f'write-out = "\\n{marker}%{{http_code}}"',
    ]
    for name, value in request.headers.multi_items():
        if name.lower() not in {"host", "content-length", "connection", "accept-encoding"}:
            config_lines.append(
                f'header = "{_curl_config_escape(f"{name}: {value}")}"'
            )
    config_lines.append('header = "Connection: close"')
    # httpx 默认声明支持 gzip，但 curl 不会在未启用 --compressed 时自动解压。
    config_lines.append('header = "Accept-Encoding: identity"')
    body = request.content
    if body:
        config_lines.append(f'data-binary = "{_curl_config_escape(body.decode("utf-8"))}"')

    try:
        completed = subprocess.run(
            [curl_exe, "--noproxy", "*", "--config", "-"],
            input="\n".join(config_lines) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=REQUEST_TIMEOUT_SECONDS + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Windows TLS 请求超时") from exc
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"curl 退出码 {completed.returncode}")
    if marker not in completed.stdout:
        raise RuntimeError("Windows TLS 请求缺少 HTTP 状态码")
    response_body, status_text = completed.stdout.rsplit(marker, 1)
    return httpx.Response(
        int(status_text.strip()),
        content=response_body.rstrip("\r\n").encode("utf-8"),
        request=request,
    )


class FallbackHttpClient(httpx.Client):
    """按广告同步脚本的策略，在 Windows TLS、直连和系统代理间容错。"""

    def __init__(self, **extra: Any):
        options: dict[str, Any] = {
            "trust_env": False,
            "http2": False,
            "timeout": REQUEST_TIMEOUT_SECONDS,
            "limits": httpx.Limits(max_keepalive_connections=0, max_connections=10),
        }
        options.update(extra)
        super().__init__(**options)
        proxy = configured_proxy()
        self._proxy_client = (
            httpx.Client(**{**options, "proxy": proxy}) if proxy else None
        )
        self._preferred_route: str | None = None

    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        routes = ["windows_tls", "direct"]
        if self._proxy_client is not None:
            routes.append("system_proxy")
        if self._preferred_route in routes:
            routes.remove(self._preferred_route)
            routes.insert(0, self._preferred_route)

        errors: list[str] = []
        for route in routes:
            try:
                if route == "windows_tls":
                    response = _send_with_windows_tls(request)
                elif route == "direct":
                    response = super().send(request, **kwargs)
                else:
                    assert self._proxy_client is not None
                    response = self._proxy_client.send(request, **kwargs)
                self._preferred_route = route
                return response
            except Exception as exc:
                label = {
                    "windows_tls": "Windows TLS",
                    "direct": "Python 直连",
                    "system_proxy": "系统代理",
                }[route]
                errors.append(f"{label}：{exc}")
        raise httpx.ConnectError("；".join(errors), request=request)

    def close(self) -> None:
        if self._proxy_client is not None:
            self._proxy_client.close()
        super().close()


def create_http_client(**extra: Any) -> httpx.Client:
    return FallbackHttpClient(**extra)


def proxy_hint() -> str:
    proxy = configured_proxy()
    suffix = f"，失败后尝试系统代理 {proxy}" if proxy else ""
    return f"Notion 连接会依次尝试 Windows TLS、Python 直连{suffix}。"

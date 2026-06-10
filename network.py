from __future__ import annotations

import os
import sys
from typing import Any

import httpx


def _read_windows_proxy() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            proxy_enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            if not proxy_enabled:
                return None
            proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
    except OSError:
        return None

    if not proxy_server:
        return None

    # Windows can store "http=host:port;https=host:port" or a bare "host:port".
    parts = dict(
        item.split("=", 1)
        for item in proxy_server.split(";")
        if "=" in item and item.split("=", 1)[1].strip()
    )
    proxy = parts.get("https") or parts.get("http") or proxy_server.split(";", 1)[0]
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return proxy


def configured_proxy() -> str | None:
    value = os.getenv("NOTION_PROXY", "").strip()
    if value.lower() in {"direct", "none", "off", "false", "0"}:
        return None
    if value:
        return value
    return _read_windows_proxy()


def create_http_client(**extra: Any) -> httpx.Client:
    proxy = configured_proxy()
    kwargs: dict[str, Any] = {
        "trust_env": False,
        "http2": False,
        "timeout": 60,
        # Avoid stale keep-alive sockets after Notion or the proxy closes a tunnel.
        "limits": httpx.Limits(max_keepalive_connections=0, max_connections=10),
    }
    if proxy:
        kwargs["proxy"] = proxy
    kwargs.update(extra)
    return httpx.Client(**kwargs)


def proxy_hint() -> str:
    proxy = configured_proxy()
    if proxy:
        return f"当前会通过代理访问 Notion：{proxy}"
    return "当前会直连 Notion；如直连被重置，可在 .env 添加 NOTION_PROXY=http://127.0.0.1:7897"

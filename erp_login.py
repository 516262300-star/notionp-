from __future__ import annotations
import argparse
from erp_client import ErpClient, ErpError
from erp_desktop_auth import DesktopLoginRequired, client_action, get_client_cookies

def main() -> int:
    parser = argparse.ArgumentParser(description="Leedis 客户端登录和会话检查")
    parser.add_argument("command", choices=("login", "open", "status"))
    args = parser.parse_args()
    try:
        if args.command == "login":
            client_action("login")
            print("客户端已登录；可以打开系统或生成周报。")
        else:
            get_client_cookies(force=True)
            with ErpClient() as client:
                if not client.check_login():
                    raise ErpError("请在 Leedis 桌面客户端登录后重试。")
            print("客户端 ERP 登录状态正常。")
        return 0
    except (ErpError, DesktopLoginRequired) as exc:
        print(f"系统登录未就绪：{exc}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from erp_client import ErpClient, ErpError
from erp_session import delete_session


def build_parser() -> argparse.ArgumentParser:
    default_phone = os.getenv("ERP_PHONE", "").strip()
    default_password = os.getenv("ERP_PASSWORD", "").strip()
    parser = argparse.ArgumentParser(description="利德仕系统登录和会话检查")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send = subparsers.add_parser("send-code", help="发送手机动态码")
    send.add_argument("--phone", default=default_phone)

    login = subparsers.add_parser("login", help="使用长期登录密码登录")
    login.add_argument("--phone", default=default_phone)
    login.add_argument("--password", default=default_password)

    subparsers.add_parser("status", help="检查加密会话是否仍有效")
    subparsers.add_parser("logout", help="删除本机加密会话")
    return parser


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    if args.command in {"send-code", "login"} and not args.phone:
        print("请通过 --phone 传入手机号，或在 .env 中填写 ERP_PHONE。")
        return 2
    if args.command == "login" and not args.password:
        print("请通过 --password 传入登录密码，或在 .env 中填写 ERP_PASSWORD。")
        return 2
    if args.command == "logout":
        delete_session()
        print("已删除本机系统登录会话。")
        return 0

    try:
        with ErpClient() as client:
            if args.command == "send-code":
                client.send_sms(args.phone)
                print("验证码已发送；如该验证码是长期密码，请妥善保存在本机 .env。")
            elif args.command == "login":
                client.login(args.phone, args.password)
                print("系统登录成功，会话已用 Windows 当前用户加密保存。")
            elif args.command == "status":
                if client.check_login():
                    print("系统登录状态正常。")
                else:
                    print("系统尚未登录或会话已过期。")
                    return 1
        return 0
    except ErpError as exc:
        print(f"系统登录失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

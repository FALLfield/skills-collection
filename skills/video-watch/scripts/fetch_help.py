#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal helper: prepare inbox/ and print the three-tier instructions.

Any agent can run this without extra context:

    python scripts/fetch_help.py --init
    python scripts/fetch_help.py --url "https://..."

It does not download, does not touch the browser, and does not read cookies.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

# Allow running as a script from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_protocol as proto  # noqa: E402


def guess_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    hints = {
        "xiaohongshu.com": "xiaohongshu",
        "xhslink.com": "xiaohongshu",
        "rednote.com": "xiaohongshu",
        "douyin.com": "douyin",
        "iesdouyin.com": "douyin",
        "bilibili.com": "bilibili",
        "b23.tv": "bilibili",
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "wikimedia.org": "wikimedia",
        "wikipedia.org": "wikimedia",
    }
    for key, name in hints.items():
        if key in host:
            return name
    return "other"


def main() -> None:
    p = argparse.ArgumentParser(
        description="准备 inbox/ 文件夹，或预览某条链接失败时要请用户做的最短步骤。"
    )
    p.add_argument("--init", action="store_true", help="创建 inbox/ 并写入说明")
    p.add_argument("--url", default="", help="可选，根据链接平台预览档 2 / 档 3 指引")
    p.add_argument("--inbox", default="", help="inbox 路径，默认包内 inbox/")
    p.add_argument("--out", default="", help="预览指引里写到的输出目录")
    args = p.parse_args()

    inbox = proto.ensure_inbox(Path(args.inbox).expanduser() if args.inbox else proto.default_inbox())
    out = Path(args.out).expanduser() if args.out else proto.default_out()

    if not args.url:
        print(f"已准备收件夹：{inbox}")
        print("请用户把视频文件或自己导出的 cookies.txt 拖进这个文件夹。")
        print("然后运行：")
        print(f"  python scripts/watch_video.py --auto {inbox} --out {out}")
        print("或对一条公开链接：")
        print(f"  python scripts/watch_video.py --auto \"https://...\" --out {out}")
        print("脚本会自动判断走档 1（直接下载）、档 2（请用户做一个简单操作）还是档 3（只能处理文字）。")
        return

    platform = guess_platform(args.url)
    # Preview only: we do not claim a download was attempted.
    if platform in {"wikimedia"}:
        message = (
            f"这是 {proto.platform_label(platform)} 链接。多数情况下可走档 1 全自动下载。"
            "请直接运行："
            f"\n  python scripts/watch_video.py --auto \"{args.url}\" --out {out}"
        )
        status = proto.build_status(
            status="ok",
            tier=1,
            reason_code="ok",
            message=message,
            platform=platform,
            url=args.url,
            out_dir=out,
            inbox=inbox,
        )
        # Preview of a likely-auto link is not a completed run.
        status["status"] = "preview"
        status["note"] = "这只是预览，尚未真正下载。"
    else:
        reason = "need_cookies" if platform in {"douyin", "xiaohongshu", "bilibili", "youtube"} else "other"
        if platform == "youtube":
            message = (
                "YouTube 有时可以全自动下载，但不作承诺。若自动失败，请任选下面一种简单做法。"
            )
        elif platform == "bilibili":
            message = (
                "B 站链接会先尝试自动下载。本包在未登录测试环境中未能取到（常见 HTTP 412）。"
                "若自动失败，请任选下面一种简单做法。用你自己的 cookie 再试是否有效，尚未在真实登录态下测过。"
            )
        else:
            message = (
                f"{proto.platform_label(platform)} 链接在未登录、无 cookie 时通常不能全自动下载。"
                "请任选下面一种简单做法。用你自己的 cookie 再试是否有效，尚未在真实登录态下测过。"
            )
        steps = proto.user_steps(
            platform=platform, url=args.url, inbox=inbox, out_dir=out, reason=reason
        )
        status = proto.build_status(
            status="need_user",
            tier=2,
            reason_code=reason,
            message=message,
            platform=platform,
            url=args.url,
            out_dir=out,
            inbox=inbox,
            user_steps_list=steps,
        )
    print(proto.format_human(status), end="")
    print()
    print(proto.STATUS_MARKER)
    print(proto.emit_status(status, out_dir=None))


if __name__ == "__main__":
    main()

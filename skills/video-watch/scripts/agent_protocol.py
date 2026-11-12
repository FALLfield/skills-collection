#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Three-tier download protocol shared by watch_video.py and fetch_help.py.

This module is intentionally free of any one agent's APIs. It only builds
structured status JSON and short Chinese instructions a human can follow.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".ogv"}

# Official store listings verified on 2026-11-11 (Asia/Macau, UTC+8).
# We only list extensions that ship from official stores, are open source,
# and whose listings say cookies stay on the device / no data collection.
COOKIE_EXTENSIONS = [
    {
        "browser": "Chrome / Edge / Chromium",
        "name": "Get cookies.txt LOCALLY",
        "store": "Chrome Web Store",
        "url": "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc",
        "source": "https://github.com/kairi003/Get-cookies.txt-LOCALLY",
        "note": "扩展页写明 cookie 只在本地导出、不会外传；开源。作者声明与早年被指存在恶意代码的「Get cookies.txt」不是同一款。",
    },
    {
        "browser": "Firefox",
        "name": "cookies.txt",
        "store": "Firefox Add-ons（AMO 官方）",
        "url": "https://addons.mozilla.org/firefox/addon/cookies-txt/",
        "source": "https://github.com/hrdl-github/cookies-txt",
        "note": "官方商店上架、开源（GPL-3.0）；扩展页写明不收集数据。导出的是 Netscape cookies.txt，可供 yt-dlp 使用。",
    },
]

TIER2_REASONS = {"cookies", "need_cookies", "login", "waf", "ratelimit", "unsupported"}
TIER3_ALWAYS = True

# reason_code values agents should switch on
REASON_OK = "ok"
REASON_NEED_COOKIES = "need_cookies"
REASON_LOGIN = "login"
REASON_WAF = "waf"
REASON_RATELIMIT = "ratelimit"
REASON_GEO = "geo"
REASON_RESTRICTED = "restricted"
REASON_UNSUPPORTED = "unsupported"
REASON_NO_MEDIA = "no_media"
REASON_CORRUPT = "corrupt"
REASON_OTHER = "other"


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_inbox() -> Path:
    return package_root() / "inbox"


def default_out() -> Path:
    return package_root() / "out" / "auto"


def looks_like_url(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.match(r"^https?://", value.strip(), re.I))


def looks_like_netscape(path: Path) -> bool:
    """Heuristic: Netscape cookie files, not arbitrary .txt."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    if "HTTP Cookie File" in head or "Netscape" in head:
        return True
    # tab-separated cookie lines, 7 fields
    for line in head.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            if s.startswith("#HttpOnly_"):
                s = s[len("#HttpOnly_"):]
            else:
                continue
        parts = s.split("\t")
        if len(parts) >= 7 and ("." in parts[0] or parts[0].startswith("#")):
            return True
    return False


def find_inbox_cookies(inbox: Path) -> Path | None:
    if not inbox.is_dir():
        return None
    preferred = [
        inbox / "cookies.txt",
        inbox / "cookies.netscape",
        inbox / "cookies.txt.txt",
    ]
    for p in preferred:
        if p.is_file() and looks_like_netscape(p):
            return p
    cands = []
    for p in inbox.iterdir():
        if p.is_file() and p.suffix.lower() in {".txt", ".netscape"} and looks_like_netscape(p):
            cands.append(p)
    if not cands:
        return None
    cands.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[0]


def find_inbox_video(inbox: Path) -> Path | None:
    if not inbox.is_dir():
        return None
    cands = [p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not cands:
        return None
    cands.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[0]


def ensure_inbox(inbox: Path | None = None) -> Path:
    path = inbox or default_inbox()
    path.mkdir(parents=True, exist_ok=True)
    readme = path / "README.md"
    if not readme.exists():
        readme.write_text(
            "把视频文件（mp4 / webm / mkv / mov）或你自己导出的 cookies.txt 放进这个文件夹，\n"
            "然后让 agent 运行：\n\n"
            "    python scripts/watch_video.py --auto inbox --out ./out/run1\n\n"
            "不要把 cookie 文件发给别人或发到聊天里。用完可以删除。\n"
            "本工具不会从浏览器代取 cookie，也不会绕过登录。\n",
            encoding="utf-8",
        )
    return path


def normalize_reason(kind: str) -> str:
    mapping = {
        "cookies": REASON_NEED_COOKIES,
        "need_cookies": REASON_NEED_COOKIES,
        "login": REASON_LOGIN,
        "waf": REASON_WAF,
        "ratelimit": REASON_RATELIMIT,
        "geo": REASON_GEO,
        "restricted": REASON_RESTRICTED,
        "unsupported": REASON_UNSUPPORTED,
        "no_media": REASON_NO_MEDIA,
        "corrupt": REASON_CORRUPT,
        "ok": REASON_OK,
        "other": REASON_OTHER,
    }
    return mapping.get(kind, REASON_OTHER)


def platform_label(platform: str | None) -> str:
    return {
        "bilibili": "B 站",
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "youtube": "YouTube",
        "wikimedia": "Wikimedia",
        "local": "本机文件",
    }.get(platform or "", platform or "该网站")


def _cookie_ext_text() -> str:
    lines = []
    for ext in COOKIE_EXTENSIONS:
        lines.append(
            f"- {ext['browser']}：在官方商店安装「{ext['name']}」（{ext['store']}）\n"
            f"  {ext['url']}\n"
            f"  {ext['note']}\n"
            f"  源码：{ext['source']}"
        )
    return "\n".join(lines)


def _os_record_lines() -> str:
    return (
        "- 手机 iPhone：从右上角下滑打开控制中心，点「屏幕录制」，打开对应 App 播放后再开始；录完后到「照片」取出文件。\n"
        "- 手机 Android：下拉快捷设置，点「录屏」，打开对应 App 播放后录制；录完后到相册或「文件」取出。\n"
        "- Windows：按 Win + G 打开 Xbox 游戏栏开始录制，或按 Win + Alt + R。\n"
        "- macOS：按 Shift + Command + 5，选择「录制所选部分」或「录制整个屏幕」。"
    )


def _save_file_detail(platform: str, where: str, inbox_s: str, retry: str) -> str:
    """Platform-specific, copy-pasteable Chinese steps. One option, not a sequence of three."""
    put = (
        f"把得到的视频文件（mp4 / mov / webm / mkv 均可）拖进这个文件夹：\n  {inbox_s}\n"
        f"放好后告诉我「继续」，我会运行：\n  {retry}"
    )
    record = (
        "如果没有保存入口，请用系统自带录屏，只录你有权观看的这一段：\n"
        + _os_record_lines()
    )
    if platform == "bilibili":
        return (
            "B 站普通稿件通常没有「保存成 mp4」按钮；App 里的「缓存」存在应用内部，不容易直接拷出来。"
            "请用系统自带录屏，只录你有权观看的这一条（这是最省事、也最稳的做法）：\n"
            + _os_record_lines() + "\n"
            "若你是这条稿件的 UP 主，也可以在「创作中心」下载原片。\n"
            + put
        )
    if platform == "douyin":
        return (
            "打开抖音 App，进入这条你有权观看的视频，然后：\n"
            "1. 点右下角或底部的「分享」。\n"
            "2. 若出现「保存到相册」或「保存视频」，点它；再从手机相册把文件拷到电脑上的 inbox/ 文件夹（见下面的路径）。\n"
            "3. 若没有保存入口（作者未开放保存），请改用系统自带录屏，只录这一段：\n"
            + _os_record_lines() + "\n"
            + put
        )
    if platform == "xiaohongshu":
        return (
            "打开小红书 App，进入这条你有权观看的视频或笔记，然后：\n"
            "1. 点右下角或底部的「分享」。\n"
            "2. 若出现「保存视频」或「保存到相册」，点它；再从手机相册把文件拷到电脑上的 inbox/ 文件夹（见下面的路径）。\n"
            "3. 若没有保存入口，请改用系统自带录屏，只录这一段：\n"
            + _os_record_lines() + "\n"
            + put
        )
    if platform == "youtube":
        return (
            "YouTube 普通观看页通常没有官方「另存为文件」按钮（会员下载功能也不在本工具范围内）。\n"
            "请用系统自带录屏，只录你有权观看的这一段：\n"
            + _os_record_lines() + "\n"
            + put
        )
    return (
        f"{where}，用自带的「保存视频 / 下载 / 分享到文件」。\n"
        + record + "\n"
        + put
    )


def _cookies_from_browser_detail(platform: str, label: str, inbox_s: str, url_s: str, retry: str) -> str:
    site = {
        "bilibili": "www.bilibili.com",
        "douyin": "www.douyin.com",
        "xiaohongshu": "www.xiaohongshu.com",
        "youtube": "www.youtube.com",
    }.get(platform, "该网站")
    login_note = (
        f"请确认：你要运行命令的这台电脑上，浏览器已经登录了 {site}。"
        "手机 App 里的登录态不能直接给这条命令用。"
    )
    if platform == "xiaohongshu":
        login_note += " 若浏览器会跳到 rednote.com 登录页，请先在浏览器里完成登录再运行命令。"
    return (
        "请在你自己的电脑上按下面做（只需这一种；我不会替你执行，也不会读取你的浏览器）。\n"
        f"1. {login_note}\n"
        "2. 若还没安装 yt-dlp，先在终端执行：pip install yt-dlp\n"
        "   （或按 https://github.com/yt-dlp/yt-dlp 的说明安装。）\n"
        "3. 建议先完全退出该浏览器（Chrome / Edge 在后台仍运行时，有时会读不到 cookie），再打开终端，复制运行：\n\n"
        f"  yt-dlp --cookies-from-browser chrome --no-playlist "
        f"-f \"bv*[height<=720]+ba/b[height<=720]/best\" "
        f"-o \"{inbox_s}/media.%(ext)s\" \"{url_s}\"\n\n"
        "4. 把上面的 chrome 换成你实际在用的浏览器：chrome、firefox、edge、safari、brave、chromium。\n"
        f"5. 下载成功后，文件会出现在 {inbox_s}，告诉我「继续」，我会运行：\n  {retry}\n"
        f"这条路径是否适用于「{label}」，本包未在真实登录态下测过，需要你本机验证，不能保证一定成功。"
    )


def _export_extension_detail(label: str, inbox_s: str, retry_url: str) -> str:
    return (
        "请在你自己的电脑上按下面做（只需这一种；我不会代取，也不会从浏览器读取）。\n"
        "1. 只从官方商店安装下面这类开源扩展，不要用不明来源的「cookie 导出」工具：\n"
        f"{_cookie_ext_text()}\n"
        f"2. 用同一浏览器打开并登录「{label}」，最好停留在这条视频的页面上。\n"
        "3. 按扩展说明导出 Netscape 格式的 cookies.txt（扩展页写明 cookie 只在本地导出、不会外传）。\n"
        f"4. 把文件放到：\n  {inbox_s}/cookies.txt\n"
        "   不要把这个文件发给别人，也不要粘到聊天里。\n"
        f"5. 告诉我「继续」，我会运行：\n  {retry_url}\n"
        "用完可删除扩展和 cookies.txt。"
        f"\n用你自己的 cookie 重新尝试「{label}」，本包未在真实登录态下测过，不得视为一定有效。"
    )


def user_steps(
    *,
    platform: str,
    url: str | None,
    inbox: Path,
    out_dir: Path,
    reason: str,
    python_bin: str = "python",
) -> list[dict[str, str]]:
    """At most three alternatives, not a forced sequence. Each is ≤ a few actions."""
    inbox_s = str(inbox)
    url_s = url or "<视频链接>"
    label = platform_label(platform)
    retry = f"{python_bin} scripts/watch_video.py --auto {inbox_s} --out {out_dir}"
    retry_url = f'{python_bin} scripts/watch_video.py --auto "{url_s}" --out {out_dir}'
    if url and platform not in {"", "other", "local"}:
        where = f"在 {label} 的 App 或网页里"
    else:
        where = "在相应 App 或网页里"

    steps: list[dict[str, str]] = []

    # Restricted/paid content: do not suggest cookies as a way to unlock payment/DRM.
    suggest_cookies = reason in {
        REASON_NEED_COOKIES, REASON_LOGIN, REASON_WAF, REASON_RATELIMIT,
        REASON_UNSUPPORTED, REASON_OTHER,
    }

    steps.append({
        "n": "1",
        "kind": "save_file",
        "title": "最省事（推荐）：自己保存或录屏，把文件放进 inbox/",
        "detail": _save_file_detail(platform, where, inbox_s, retry),
    })

    if reason == REASON_NO_MEDIA:
        return steps[:1]

    if suggest_cookies:
        steps.append({
            "n": "2",
            "kind": "cookies_from_browser",
            "title": "或者：在你自己的电脑上用一条命令下载（不经过我）",
            "detail": _cookies_from_browser_detail(platform, label, inbox_s, url_s, retry),
        })
        steps.append({
            "n": "3",
            "kind": "export_extension",
            "title": "或者：用官方商店里的扩展导出 cookies.txt，让我再试一次链接",
            "detail": _export_extension_detail(label, inbox_s, retry_url),
        })
    else:
        # geo / restricted: only the save-file path, plus a short cannot-bypass note
        steps.append({
            "n": "2",
            "kind": "note",
            "title": "不会帮你绕过会员、付费或地区限制",
            "detail": (
                "如果这是会员、付费或受 DRM 保护的内容，本工具不会尝试解锁。"
                "只有在你本来就有权观看时，才用上面的保存或录屏方式提供文件。"
            ),
        })

    return steps[:3]


def tier3_capabilities(platform: str) -> dict[str, list[str]]:
    label = platform_label(platform)
    return {
        "can_do_without_video": [
            "根据你提供的标题、简介、评论或你自己复制的字幕文本，帮忙整理要点、列大纲或起草笔记",
            "记住这条链接，等你把视频文件或 cookies.txt 放进 inbox/ 后再做画面分析",
            f"说明「{label}」当前为什么不能自动下载，以及你可以做的最短手动步骤",
        ],
        "cannot_do_without_video": [
            "看懂画面、硬字幕、镜头切换和节奏（这些必须有视频文件）",
            "生成分镜联系图、时间轴和带关键帧的报告",
            "口播转写（没有音轨就无法转写）",
            "绕过登录、风控、签名保护、DRM 或去水印",
        ],
    }


def redact_text(text: str, extra_secrets: list[str] | None = None) -> str:
    """Strip cookie values and obvious secrets so they never reach logs or JSON."""
    if not text:
        return text
    out = text
    for secret in extra_secrets or []:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "[redacted]")
    patterns = [
        re.compile(r"(SESSDATA=)[^\s;\"']+", re.I),
        re.compile(r"(bili_jct=)[^\s;\"']+", re.I),
        re.compile(r"(sessionid=)[^\s;\"']+", re.I),
        re.compile(r"(sid_guard=)[^\s;\"']+", re.I),
        re.compile(r"(sessionid_ss=)[^\s;\"']+", re.I),
        re.compile(r"(web_session=)[^\s;\"']+", re.I),
        re.compile(r"(--auth\s+)[\"']?[^\"'\s]+", re.I),
    ]
    for pat in patterns:
        out = pat.sub(r"\1[redacted]", out)
    return out


def cookie_secret_values(cookie_file: Path | None) -> list[str]:
    """Load values only for redaction. Never log them."""
    if not cookie_file or not cookie_file.is_file():
        return []
    secrets: list[str] = []
    try:
        raw = cookie_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#HttpOnly_"):
            s = s[len("#HttpOnly_"):]
        elif not s or s.startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) >= 7 and parts[6] and parts[6] not in {"TRUE", "FALSE"}:
            secrets.append(parts[6])
    return secrets


def build_status(
    *,
    status: str,
    tier: int,
    reason_code: str,
    message: str,
    platform: str | None = None,
    url: str | None = None,
    out_dir: Path | str | None = None,
    inbox: Path | str | None = None,
    user_steps_list: list[dict[str, str]] | None = None,
    extras: dict[str, Any] | None = None,
    secrets: list[str] | None = None,
) -> dict[str, Any]:
    cap = tier3_capabilities(platform or "") if tier >= 2 or status != "ok" else {}
    payload: dict[str, Any] = {
        "status": status,
        "tier": tier,
        "reason_code": normalize_reason(reason_code),
        "platform": platform,
        "url": url,
        "out_dir": str(out_dir) if out_dir else None,
        "inbox": str(inbox) if inbox else None,
        "message": redact_text(message, secrets),
        "user_steps": user_steps_list or [],
        "can_do_without_video": cap.get("can_do_without_video") or [],
        "cannot_do_without_video": cap.get("cannot_do_without_video") or [],
    }
    if extras:
        for k, v in extras.items():
            if k not in payload:
                payload[k] = v
    return payload


def format_human(status: dict[str, Any]) -> str:
    """Chinese text an agent can show the user as-is."""
    lines = [status.get("message") or ""]
    steps = status.get("user_steps") or []
    if steps:
        lines.append("")
        lines.append("请你任选下面一种做法（不是三步都要做）：")
        for st in steps:
            lines.append(f"\n{st.get('n')}. {st.get('title')}")
            lines.append(st.get("detail") or "")
    if status.get("status") != "ok" and status.get("cannot_do_without_video"):
        lines.append("")
        lines.append("在还没有视频文件之前，我做不到：")
        for item in status["cannot_do_without_video"]:
            lines.append(f"- {item}")
        lines.append("我仍然可以：")
        for item in status.get("can_do_without_video") or []:
            lines.append(f"- {item}")
    lines.append("")
    lines.append("仅用于学习分析你有权查看的视频。不要把 cookies.txt 发给别人或发到聊天里。")
    return "\n".join(lines).strip() + "\n"


def emit_status(status: dict[str, Any], out_dir: Path | None = None, *, also_human: bool = True) -> str:
    """Write status.json and return the JSON string (secrets already redacted)."""
    text = json.dumps(status, ensure_ascii=False, indent=2)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "status.json").write_text(text + "\n", encoding="utf-8")
    return text


STATUS_MARKER = "[video-watch-status]"

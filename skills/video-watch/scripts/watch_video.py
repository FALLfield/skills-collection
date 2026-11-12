#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公开视频拆解管线（纯 CPU）。

输入：公开链接、搜索关键词，或用户本机已有的视频文件。
输出：分镜表、口播/字幕、镜头节奏、关键帧联系图、HTML/Markdown 报告。

合规边界：
- 只处理无需登录即可公开访问的视频，或用户自行放置的 cookie 文件（--cookies）。
- 不代取 cookie，不从浏览器读取，不绕过登录，不破解签名或 DRM，不去水印，不抓私人/仅好友可见内容，不搬运付费内容。
- 下载器以用户自己安装的依赖方式调用，不在包内打包第三方源码。
- 若某平台的开源工具实质是在绕过平台防护（模拟浏览器指纹、还原签名参数、去水印），不接入。
- 平台拒绝未登录访问时如实失败，并提示改用本机文件、公开可取平台，或用户自己提供的 cookie 文件。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import agent_protocol as proto

FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_INDEX_SC = 2  # Noto Sans CJK SC
DEFAULT_MAX_DURATION = 300  # seconds
DEFAULT_MAX_FILESIZE = 80 * 1024 * 1024
DEFAULT_SCENE_TH = 0.32
DEFAULT_MAX_SHOTS = 24
INTERVAL_FALLBACK = 6.0  # seconds, used when scene-detect finds too few cuts

PLATFORM_HINTS = {
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


def which_or_die(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise SystemExit(f"找不到命令 {name}，请先安装 ffmpeg/ffprobe。")
    return p


def run(cmd: list[str], check: bool = True, capture: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def _clean_title(name: str | None) -> str:
    if not name:
        return ""
    cleaned = unquote(str(name)).strip()
    return cleaned


def guess_platform(url: str | None) -> str:

    if not url:
        return "local"
    host = (urlparse(url).hostname or "").lower()
    for key, name in PLATFORM_HINTS.items():
        if key in host:
            return name
    return "other"


def ffprobe_info(path: Path) -> dict[str, Any]:
    ffprobe = which_or_die("ffprobe")
    try:
        raw = run([
            ffprobe, "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]).stdout
        data = json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        raise SystemExit(f"无法读取该文件，可能已损坏或不是音视频：{path}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    return {
        "duration": duration,
        "size": int(fmt.get("size") or path.stat().st_size),
        "width": width,
        "height": height,
        "vcodec": video.get("codec_name"),
        "acodec": audio.get("codec_name"),
        "fps": _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "orientation": "vertical" if height > width else "landscape",
    }


def _parse_fps(s: str | None) -> float | None:
    if not s or s == "0/0":
        return None
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else None
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def format_ts(sec: float) -> str:
    if sec < 0:
        sec = 0
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h:d}:{m:02d}:{s:06.3f}"
    return f"{int(m):02d}:{s:06.3f}"


def format_ts_short(sec: float) -> str:
    if sec < 0:
        sec = 0
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


# -------------------- acquire --------------------

def find_tool(name: str) -> str | None:
    """Locate an optional downloader on PATH or beside the current interpreter.

    Do not hardcode a .venv path. Do not Path.resolve() the interpreter:
    a venv's python is often a symlink to /usr/bin/python3.
    """
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        Path(sys.executable).parent / name,
        Path(sys.prefix) / "bin" / name,
        Path(sys.prefix) / "Scripts" / f"{name}.exe",
        Path(sys.executable).parent / f"{name}.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def find_yt_dlp() -> str:
    found = find_tool("yt-dlp")
    if found:
        return found
    raise SystemExit(
        "找不到 yt-dlp。请先按 README 用 python3 -m venv 创建虚拟环境，"
        "pip install -r requirements.txt，再运行本脚本"
        "（不必先 source activate，用该环境的 python 直接调用即可）。"
    )


def classify_download_error(err: str) -> str:
    """Map a downloader's stderr/stdout to a coarse, user-facing reason.

    Always classify the raw downloader output, never our own fallback text:
    the fallback mentions DRM / 付费 and would otherwise be mis-labelled.
    More specific signals (cookies, login, unsupported, HTTP codes) are
    checked before broad words like DRM.
    """
    e = (err or "").lower()
    if "precondition failed" in e or re.search(r"(http(?:\s+error)?\s*[:#-]?)\s*412\b", e) or "httpstatuserror" in e:
        return "waf"
    if (
        "too many requests" in e
        or "not a bot" in e
        or "confirm you’re not" in e
        or "confirm you're not" in e
        or re.search(r"(http(?:\s+error)?\s*[:#-]?)\s*429\b", e)
    ):
        return "ratelimit"
    if "fresh cookies" in e or "cookies are needed" in e or "please provide cookies" in e or "cookie-related" in e:
        return "cookies"
    if "unsupported url" in e or "unsupported website" in e:
        # A login-page URL reported as "Unsupported URL" is still a login wall.
        if "/login" in e or "sign in" in e or "login required" in e or "需要登录" in e or "未登录" in e:
            return "login"
        return "unsupported"
    if "sign in" in e or "login required" in e or "/login" in e or "需要登录" in e or "未登录" in e:
        return "login"
    if "not available in your country" in e or "not available in your region" in e or ("地区" in e and ("限制" in e or "不可用" in e)):
        return "geo"
    # Do not match the word DRM inside our own phrases such as "不破解签名或 DRM".
    if re.search(r"\bwidevine\b", e) or "only available for premium" in e:
        return "restricted"
    if re.search(r"(?<![\u4e00-\u9fff])drm(?![\w])", e) and "不破解" not in e:
        return "restricted"
    if "大会员" in e or "充电专属" in e or "members only" in e or "premium-only" in e:
        return "restricted"
    if "付费" in e and "不破解" not in e and "本工具不登录" not in e:
        return "restricted"
    return "other"


def _reason_zh(kind: str) -> str:
    return {
        "waf": "平台或中间层拒绝了请求（常见 HTTP 412 / 防火墙），不一定是链接本身无效。",
        "ratelimit": "请求过于频繁或被判定为机器人（常见 HTTP 429）。",
        "geo": "该内容有地区限制，当前网络环境取不到。",
        "restricted": "该内容可能需要会员、付费或受 DRM 保护，本工具不会绕过这类限制。",
        "cookies": "下载器提示需要 cookie。本工具不会代取，也不会从浏览器读取。",
        "login": "该链接在未登录条件下无法访问（例如跳到登录页）。",
        "unsupported": "所用下载器不支持这条链接。",
        "other": "未能归类的失败。",
    }.get(kind, "未能归类的失败。")


class DownloadFailed(RuntimeError):
    """Download failed. `.raw` is the downloader output used for classification."""

    def __init__(self, raw: str, *, platform: str = "", tried: list[str] | None = None):
        self.raw = raw or ""
        self.platform = platform
        self.tried = tried or []
        self.kind = classify_download_error(self.raw)
        super().__init__(fallback_message(platform, self.raw, tried=self.tried))


def fallback_message(platform: str, err: str, tried: list[str] | None = None) -> str:
    snippet = (err or "").strip()[:400]
    kind = classify_download_error(err)
    reason = _reason_zh(kind)
    tried_txt = "、".join(tried) if tried else "yt-dlp"
    cookie_hint = (
        "若你已用自己的账号在本机登录，并自行导出了 Netscape 格式的 cookie 文件，"
        "可以把文件路径交给 --cookies 再试一次。我们不代取 cookie，也不从浏览器读取。"
    )
    file_hint = (
        "也可以在自己的设备上保存或录屏后，用 --file 提交本机文件。"
        "本工具不登录、不破解签名或 DRM、不去水印，也不接入用于绕过平台防护的工具。"
        "仅用于学习分析自己有权查看的视频。"
    )
    if platform in {"xiaohongshu", "douyin"}:
        return (
            f"未能直接取到该{('小红书' if platform == 'xiaohongshu' else '抖音')}链接。\n"
            f"已尝试：{tried_txt}。判断：{reason}\n"
            f"原始报错：{snippet}\n\n"
            "这些平台的多数开源下载器依赖 cookie，或通过模拟浏览器指纹、还原签名参数来绕过防护；"
            "按合规要求，本包不接入这类工具（例如 F2、Douyin_TikTok_Download_API、XHS-Downloader）。\n"
            + cookie_hint + "\n" + file_hint
        )
    if platform == "bilibili":
        extra = ""
        if "yutto" not in (tried or []) and not find_tool("yutto"):
            extra = (
                "当前环境未安装 yutto（B 站专用、需用户自行 pip install yutto）。"
                "若 yt-dlp 因风控失败，安装后可能作为回退再试一次。\n"
            )
        return (
            f"未能直接取到该 B 站链接。\n"
            f"已尝试：{tried_txt}。判断：{reason}\n"
            f"原始报错：{snippet}\n\n"
            + extra
            + cookie_hint + "\n" + file_hint
        )
    if platform == "youtube":
        return (
            "YouTube 链接本次未能取到。本包对 YouTube 不作稳定承诺。\n"
            f"已尝试：{tried_txt}。判断：{reason}\n"
            f"原始报错：{snippet}\n\n"
            + cookie_hint + "\n"
            "请改用 --file 指向你已保存、且有权分析的视频。不要尝试绕过限制。\n"
            "仅用于学习分析自己有权查看的视频。"
        )
    return (
        f"未能获取该链接。\n已尝试：{tried_txt}。判断：{reason}\n"
        f"原始报错：{snippet}\n\n"
        "请改用 --file 指向本机文件，或换一条你有权使用、且许可明确的公开直链（例如 Wikimedia 文件）。\n"
        + cookie_hint + "\n" + file_hint
    )


def _cookie_args_ytdlp(cookies: str | None) -> list[str]:
    if not cookies:
        return []
    path = Path(cookies).expanduser()
    if not path.is_file():
        raise SystemExit(f"找不到 cookie 文件：{path}。请确认路径，文件需由你自行导出并放置。")
    return ["--cookies", str(path)]


def _netscape_cookie_values(cookie_file: Path, names: set[str]) -> dict[str, str]:
    """Read selected cookie names from a Netscape cookie file. Never log the values."""
    found: dict[str, str] = {}
    try:
        raw = cookie_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#HttpOnly_"):
            s = s[len("#HttpOnly_"):]
        elif s.startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) >= 7:
            name, value = parts[5], parts[6]
            if name in names and name not in found:
                found[name] = value
    return found


def _yutto_auth_file(cookies: str | None, dest_dir: Path) -> Path:
    """Write a temporary yutto auth.toml from a user-provided Netscape cookie file.

    Always pass this file to yutto so it does not silently pick up a default
    login on the machine. Values are not printed or kept in argv.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    auth_path = dest_dir / "yutto-auth.toml"
    if cookies:
        path = Path(cookies).expanduser()
        if not path.is_file():
            raise SystemExit(f"找不到 cookie 文件：{path}。请确认路径，文件需由你自行导出并放置。")
        vals = _netscape_cookie_values(path, {"SESSDATA", "bili_jct"})
        sess = vals.get("SESSDATA", "")
        jct = vals.get("bili_jct", "")
        # Write in the inline-cookie form documented by yutto; do not echo values.
        cookie_header = "; ".join(f"{k}={v}" for k, v in (("SESSDATA", sess), ("bili_jct", jct)) if v)
        escaped = cookie_header.replace("\\", "\\\\").replace('"', '\\"')
        auth_path.write_text('[auth]\nauth = "' + escaped + '"\n', encoding="utf-8")
    else:
        auth_path.write_text("[auth]\nauth = \"\"\n", encoding="utf-8")
    return auth_path


def download_with_ytdlp(
    url: str,
    dest_dir: Path,
    max_duration: int,
    max_filesize: int,
    cookies: str | None = None,
) -> dict[str, Any]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    yt = find_yt_dlp()
    outtmpl = str(dest_dir / "media.%(ext)s")
    cmd = [
        yt,
        "--no-playlist",
        "--socket-timeout", "30",
        "--retries", "2",
        "--no-progress",
        "--newline",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "zh-Hans,zh-CN,zh,zh-Hant,zh-TW,en,en-US,en-GB",
        "--convert-subs", "vtt",
        "--max-filesize", str(max_filesize),
        "--download-sections", f"*0-{max_duration}",
        "-f", "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best",
        "-o", outtmpl,
        "--print", "after_move:filepath",
        "--print", "after_move:%(id)s",
        "--print", "after_move:%(title)s",
        "--print", "after_move:%(duration)s",
        "--print", "after_move:%(webpage_url)s",
        "--print", "after_move:%(uploader)s",
        *_cookie_args_ytdlp(cookies),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if proc.returncode != 0:
        err = (proc.stderr or "") + "\n" + (proc.stdout or "")
        raise RuntimeError(err)
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    media = _find_media(dest_dir)
    if not media:
        raise RuntimeError(proc.stdout + proc.stderr)
    meta = {
        "url": url,
        "platform": guess_platform(url),
        "id": None,
        "title": media.stem,
        "uploader": None,
        "requested_duration_cap": max_duration,
        "downloader": "yt-dlp",
        "yt_dlp_tail": lines[-8:],
    }
    return {"media": media, "subs": list(dest_dir.glob("*.vtt")), "meta": meta, "log": proc.stderr}


def download_with_yutto(
    url: str,
    dest_dir: Path,
    max_duration: int,
    max_filesize: int,
    cookies: str | None = None,
) -> dict[str, Any]:
    """Optional Bilibili fallback. yutto must be installed by the user (not bundled)."""
    exe = find_tool("yutto")
    if not exe:
        raise RuntimeError("未安装 yutto。")
    dest_dir.mkdir(parents=True, exist_ok=True)
    auth = _yutto_auth_file(cookies, dest_dir)
    # 720P cap to stay in the same size/quality band as yt-dlp. No danmaku/cover.
    # --auth-file is used even when empty so a default login on the machine is not picked up.
    # Credentials stay in the temp file, not on the command line.
    cmd = [
        exe,
        url,
        "-d", str(dest_dir),
        "-tp", "media",
        "-q", "64",
        "-w",
        "--no-danmaku",
        "--no-subtitle",
        "--no-cover",
        "--no-progress",
        "--no-color",
        "--no-inherit",
        "--auth-file", str(auth),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "") + "\n" + (proc.stdout or ""))
        media = _find_media(dest_dir)
        if not media:
            raise RuntimeError(proc.stdout + proc.stderr)
        if media.stat().st_size > max_filesize:
            media.unlink(missing_ok=True)
            raise RuntimeError(f"下载文件超过体积上限（{max_filesize} 字节），已删除。")
        meta = {
            "url": url,
            "platform": "bilibili",
            "title": media.stem,
            "downloader": "yutto",
            "requested_duration_cap": max_duration,
        }
        return {"media": media, "subs": list(dest_dir.glob("*.vtt")), "meta": meta, "log": proc.stderr}
    finally:
        # Always delete the temp auth file, including timeouts and other exceptions.
        try:
            auth.unlink(missing_ok=True)
        except OSError:
            pass


def download_with_bbdown(
    url: str,
    dest_dir: Path,
    max_duration: int,
    max_filesize: int,
    cookies: str | None = None,
) -> dict[str, Any]:
    """Optional Bilibili fallback if the user already has BBDown on PATH.

    The upstream repo is archived (last official release 1.6.3, 2024-08-14);
    we only call it when the binary is already present. We do not ship it.
    """
    exe = find_tool("BBDown") or find_tool("bbdown")
    if not exe:
        raise RuntimeError("未安装 BBDown。")
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        url,
        "--work-dir", str(dest_dir),
        "--file-pattern", "media",
        "-q", "720P 准高清",
        "--skip-ai",
        "--skip-cover",
        "--skip-subtitle",
    ]
    # BBDown's -c expects a cookie *string* on the command line. We refuse to put
    # credentials in argv; if the user supplied a cookie file, skip this downloader.
    if cookies:
        raise RuntimeError("BBDown 只能通过命令行传入 cookie 字符串，本工具不会这样做。请改用 yt-dlp 或 yutto，并把 cookie 文件交给 --cookies。")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "") + "\n" + (proc.stdout or ""))
    media = _find_media(dest_dir)
    if not media:
        raise RuntimeError(proc.stdout + proc.stderr)
    if media.stat().st_size > max_filesize:
        media.unlink(missing_ok=True)
        raise RuntimeError(f"下载文件超过体积上限（{max_filesize} 字节），已删除。")
    meta = {
        "url": url,
        "platform": "bilibili",
        "title": media.stem,
        "downloader": "BBDown",
        "requested_duration_cap": max_duration,
    }
    return {"media": media, "subs": list(dest_dir.glob("*.vtt")), "meta": meta, "log": proc.stderr}


def download_with_youget(
    url: str,
    dest_dir: Path,
    max_duration: int,
    max_filesize: int,
    cookies: str | None = None,
) -> dict[str, Any]:
    """Optional last-resort fallback if the user already has you-get on PATH."""
    exe = find_tool("you-get")
    if not exe:
        raise RuntimeError("未安装 you-get。")
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-o", str(dest_dir), "--no-caption", url]
    if cookies:
        path = Path(cookies).expanduser()
        if not path.is_file():
            raise SystemExit(f"找不到 cookie 文件：{path}。请确认路径，文件需由你自行导出并放置。")
        cmd.extend(["-c", str(path)])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "") + "\n" + (proc.stdout or ""))
    media = _find_media(dest_dir)
    if not media:
        raise RuntimeError(proc.stdout + proc.stderr)
    if media.stat().st_size > max_filesize:
        media.unlink(missing_ok=True)
        raise RuntimeError(f"下载文件超过体积上限（{max_filesize} 字节），已删除。")
    meta = {
        "url": url,
        "platform": guess_platform(url),
        "title": media.stem,
        "downloader": "you-get",
        "requested_duration_cap": max_duration,
    }
    return {"media": media, "subs": [], "meta": meta, "log": proc.stderr}


DOWNLOADERS = {
    "yt-dlp": download_with_ytdlp,
    "yutto": download_with_yutto,
    "bbdown": download_with_bbdown,
    "you-get": download_with_youget,
}


def downloaders_for(platform: str, requested: str | None = None) -> list[str]:
    """Return downloader names to try, in order. Missing optional tools are skipped later.

    Douyin / Xiaohongshu: only yt-dlp is attempted. Signature-bypass tools are not wired in.
    Bilibili: yt-dlp first, then user-installed yutto / BBDown / you-get.
    """
    if requested and requested != "auto":
        if requested not in DOWNLOADERS:
            raise SystemExit(f"未知下载器：{requested}。可选：auto、" + "、".join(DOWNLOADERS))
        return [requested]
    if platform == "bilibili":
        return ["yt-dlp", "yutto", "bbdown", "you-get"]
    return ["yt-dlp"]


def download_url(
    url: str,
    dest_dir: Path,
    max_duration: int,
    max_filesize: int,
    cookies: str | None = None,
    requested_downloader: str | None = None,
) -> dict[str, Any]:
    platform = guess_platform(url)
    names = downloaders_for(platform, requested_downloader)
    errors: list[str] = []
    tried: list[str] = []
    for name in names:
        fn = DOWNLOADERS[name]
        if name != "yt-dlp" and not (
            find_tool(name) or (name == "bbdown" and (find_tool("BBDown") or find_tool("bbdown")))
        ):
            continue
        tried.append(name)
        slot = dest_dir / name.replace("-", "")
        try:
            result = fn(url, slot, max_duration, max_filesize, cookies=cookies)
        except RuntimeError as e:
            errors.append(f"[{name}] {e}")
            continue
        # Promote the media file to dest_dir so later stages keep a stable layout.
        dest_dir.mkdir(parents=True, exist_ok=True)
        media_src: Path = result["media"]
        media_dst = dest_dir / media_src.name
        if media_src.resolve() != media_dst.resolve():
            shutil.copy2(media_src, media_dst)
            result["media"] = media_dst
        for sub in list(result.get("subs") or []):
            target = dest_dir / Path(sub).name
            if Path(sub).resolve() != target.resolve():
                shutil.copy2(sub, target)
        result["subs"] = list(dest_dir.glob("*.vtt"))
        result["meta"]["tried_downloaders"] = tried
        _assert_playable(result["media"])
        return result
    combined = "\n---\n".join(errors) if errors else "没有可用的下载器（yt-dlp 为必需依赖）。"
    raise DownloadFailed(combined, platform=platform, tried=tried or names)


def download_direct(url: str, dest_dir: Path, max_filesize: int) -> dict[str, Any]:
    """For Wikimedia / direct media URLs that yt-dlp may not need."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "media" / "download.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / "media.bin"
    cmd = [
        "curl", "-L", "--fail", "--retry", "2",
        "-A", "VideoWatchSkill/1.0 (local educational analysis)",
        "--max-filesize", str(max_filesize),
        "-o", str(tmp),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(fallback_message(guess_platform(url), proc.stderr or proc.stdout or "curl failed"))
    ext = _guess_ext(tmp)
    media = dest_dir / f"media.{ext}"
    tmp.rename(media)
    _assert_playable(media)
    return {
        "media": media,
        "subs": [],
        "meta": {
            "url": url,
            "platform": guess_platform(url),
            "title": unquote(Path(urlparse(url).path).name),
            "downloader": "curl",
        },
        "log": proc.stderr,
    }


def _guess_ext(path: Path) -> str:
    try:
        out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)]).stdout
        fmt = (json.loads(out).get("format") or {}).get("format_name") or ""
        if "webm" in fmt:
            return "webm"
        if "mp4" in fmt or "mov" in fmt or "ism" in fmt:
            return "mp4"
        if "matroska" in fmt:
            return "mkv"
    except Exception:
        pass
    return "bin"


def _find_media(dest_dir: Path) -> Path | None:
    exts = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}
    cands: list[Path] = []
    if not dest_dir.exists():
        return None
    for p in dest_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            # skip yutto/BBDown sidecars that sometimes land in nested folders — still accept them
            cands.append(p)
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_size, reverse=True)
    return cands[0]


def _is_direct_media_url(url: str) -> bool:
    """True only for actual media file hosts, not wiki File: pages (those may end in .webm)."""
    host = (urlparse(url).hostname or "").lower()
    return host == "upload.wikimedia.org" or host.endswith(".upload.wikimedia.org")


def _commons_direct_url(page_url: str) -> str | None:
    """Resolve a Commons File: page to the original media URL via public API."""
    try:
        path = unquote(urlparse(page_url).path)
        m = re.search(r"/wiki/File:(.+)$", path, re.I)
        if not m:
            return None
        title = "File:" + m.group(1)
        import urllib.request
        from urllib.parse import quote
        q = (
            "https://commons.wikimedia.org/w/api.php?"
            + "action=query&prop=imageinfo&iiprop=url&format=json&titles="
            + quote(title)
        )
        req = urllib.request.Request(q, headers={"User-Agent": "VideoWatchSkill/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        for page in (data.get("query") or {}).get("pages", {}).values():
            infos = page.get("imageinfo") or []
            if infos:
                url = infos[0].get("url")
                if url:
                    # drop tracking query if present
                    return url.split("?")[0]
    except Exception:
        return None
    return None


def _assert_playable(path: Path) -> None:
    """Reject HTML/error pages that curl or a downloader saved with a success code."""
    try:
        raw = run([
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_streams",
            str(path),
        ], check=True).stdout
        data = json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        head = b""
        try:
            head = path.read_bytes()[:80]
        except OSError:
            pass
        raise RuntimeError(
            f"下载结果不是可播放的音视频（可能是网页或错误页）：{path.name}"
            + (f"；文件开头：{head[:60]!r}" if head else "")
        )
    streams = data.get("streams") or []
    if not any(s.get("codec_type") in {"video", "audio"} for s in streams):
        raise RuntimeError(f"下载结果不含音视频流：{path.name}")


def acquire_from_search(query: str, dest_dir: Path, max_duration: int, max_filesize: int, cookies: str | None = None) -> dict[str, Any]:
    """YouTube 关键词搜索第一条（公开，不登录）。B站搜索在本环境常 412，不作默认。"""
    url = f"ytsearch1:{query}"
    result = download_url(url, dest_dir, max_duration, max_filesize, cookies=cookies, requested_downloader="yt-dlp")
    result["meta"]["search_query"] = query
    result["meta"]["platform"] = "youtube"
    return result


def acquire(
    input_value: str,
    dest_dir: Path,
    max_duration: int,
    max_filesize: int,
    mode: str,
    cookies: str | None = None,
    requested_downloader: str | None = None,
) -> dict[str, Any]:
    if mode == "file" or (mode == "auto" and Path(input_value).expanduser().exists()):
        src = Path(input_value).expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"本地文件不存在：{src}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        media = dest_dir / f"media{src.suffix.lower() or '.mp4'}"
        shutil.copy2(src, media)
        return {"media": media, "subs": [], "meta": {"url": None, "platform": "local", "title": src.name, "source_file": str(src), "downloader": "local"}, "log": ""}
    if mode == "search":
        return acquire_from_search(input_value, dest_dir, max_duration, max_filesize, cookies=cookies)
    if re.match(r"^https?://", input_value):
        platform = guess_platform(input_value)
        if _is_direct_media_url(input_value):
            return download_direct(input_value, dest_dir, max_filesize)
        # Commons 文件页优先走公开 API 拿原文件，避免被当成网页下载，也避免 yt-dlp 抽到较低分辨率。
        if platform == "wikimedia":
            direct = _commons_direct_url(input_value)
            if direct:
                try:
                    return download_direct(direct, dest_dir, max_filesize)
                except RuntimeError:
                    pass
        try:
            return download_url(input_value, dest_dir, max_duration, max_filesize, cookies=cookies, requested_downloader=requested_downloader)
        except RuntimeError:
            if platform == "wikimedia":
                direct = _commons_direct_url(input_value)
                if direct:
                    return download_direct(direct, dest_dir, max_filesize)
            raise
    if mode == "auto" and " " in input_value or not input_value.startswith("http"):
        return acquire_from_search(input_value, dest_dir, max_duration, max_filesize, cookies=cookies)
    raise SystemExit("无法识别输入。请给链接、--file 本地路径，或 --search 关键词。")


# -------------------- scenes / frames --------------------

def extract_audio(video: Path, wav: Path) -> bool:
    """Extract 16 kHz mono wav. Return True on success, False if there is no usable audio track."""
    ffmpeg = which_or_die("ffmpeg")
    try:
        run([
            ffmpeg, "-y", "-i", str(video),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(wav),
        ], timeout=120)
    except subprocess.CalledProcessError:
        if wav.exists():
            try:
                wav.unlink()
            except OSError:
                pass
        return False
    return wav.exists() and wav.stat().st_size > 0


def detect_scene_times(video: Path, threshold: float, duration: float) -> list[float]:
    """Return cut timestamps (including 0 and duration)."""
    ffmpeg = which_or_die("ffmpeg")
    # showinfo prints pts_time for selected frames
    vf = f"select='gt(scene,{threshold})',showinfo"
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(video), "-vf", vf, "-vsync", "vfr", "-f", "null", "-"],
        capture_output=True, text=True, timeout=180,
    )
    times = [0.0]
    for m in re.finditer(r"pts_time:([0-9.]+)", proc.stderr or ""):
        t = float(m.group(1))
        if t > 0.15 and (t - times[-1]) >= 0.25:
            times.append(t)
    if duration and duration - times[-1] > 0.2:
        times.append(duration)
    elif duration and times[-1] < duration:
        times[-1] = duration
    return times


def maybe_interval_sample(times: list[float], duration: float, interval: float, max_shots: int) -> tuple[list[float], str]:
    """If too few scene cuts, add interval samples so a talking-head video still has frames."""
    n_cuts = max(0, len(times) - 2)  # exclude 0 and end
    if n_cuts >= 2 or duration <= interval * 1.5:
        return times, "scene_change"
    mixed = list(times)
    t = interval
    while t < duration - 0.3:
        if all(abs(t - x) >= interval * 0.4 for x in mixed):
            mixed.append(t)
        t += interval
    mixed = sorted(set(_round_ts(x) for x in mixed))
    if mixed[0] != 0:
        mixed.insert(0, 0.0)
    if mixed[-1] < duration:
        mixed.append(duration)
    # cap
    if len(mixed) - 1 > max_shots:
        mixed = _evenly_pick(mixed, max_shots + 1)
        if mixed[0] != 0:
            mixed[0] = 0.0
        mixed[-1] = duration
    return mixed, "scene_change+interval_sample"


def _round_ts(x: float) -> float:
    return round(x, 3)


def _evenly_pick(times: list[float], n: int) -> list[float]:
    if len(times) <= n:
        return times
    # always keep first and last
    inner = times[1:-1]
    need = n - 2
    if need <= 0:
        return [times[0], times[-1]]
    idxs = [round(i * (len(inner) - 1) / (need - 1)) for i in range(need)] if need > 1 else [len(inner) // 2]
    picked = [inner[i] for i in idxs]
    return [times[0]] + picked + [times[-1]]


def extract_frame(video: Path, t: float, dest: Path, width: int = 480) -> None:
    ffmpeg = which_or_die("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run([
            ffmpeg, "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3",
            str(dest),
        ], timeout=30)
    except subprocess.CalledProcessError:
        raise SystemExit(f"无法从视频中抽取画面，文件可能已损坏或不完整：{video}")


def build_shots(times: list[float], cut_mode: str, frames_dir: Path, video: Path, max_shots: int) -> list[dict[str, Any]]:
    # times include start and end
    if len(times) - 1 > max_shots:
        times = _evenly_pick(times, max_shots + 1)
        cut_mode = cut_mode + "+capped"
    shots = []
    for i in range(len(times) - 1):
        start, end = times[i], times[i + 1]
        mid = start + min(0.4, max(0.0, (end - start) * 0.3))
        fname = frames_dir / f"shot_{i:03d}.jpg"
        extract_frame(video, mid, fname)
        shots.append({
            "index": i,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "keyframe_time": round(mid, 3),
            "keyframe": str(fname.name),
            "cut_type": cut_mode,
            "visual_description": "【待多模态模型看联系图填写：用 Read 打开 contact_sheet.png，按时间码对照本行关键帧】",
            "ocr_text": "",
            "speech": "",
            "embedded_sub": "",
        })
    return shots


def pacing_stats(shots: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    durs = [s["duration"] for s in shots if s["duration"] > 0]
    if not durs:
        return {}
    cuts = max(0, len(shots) - 1)
    cpm = (cuts / duration) * 60 if duration else 0
    return {
        "shot_count": len(shots),
        "avg_shot_sec": round(statistics.mean(durs), 3),
        "median_shot_sec": round(statistics.median(durs), 3),
        "shortest_sec": round(min(durs), 3),
        "longest_sec": round(max(durs), 3),
        "cuts": cuts,
        "cuts_per_minute": round(cpm, 2),
        "duration_sec": round(duration, 3),
    }


# -------------------- captions / ASR / OCR --------------------

def parse_vtt(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    cues = []
    # simple WebVTT parser
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("WEBVTT") and not ln.strip().startswith("NOTE") and not ln.strip().startswith("Kind:") and not ln.strip().startswith("Language:")]
        if not lines:
            continue
        time_line = None
        text_lines = []
        for ln in lines:
            if "-->" in ln:
                time_line = ln
            elif re.match(r"^\d+$", ln.strip()):
                continue
            else:
                # drop cue settings / tags
                cleaned = re.sub(r"<[^>]+>", "", ln)
                cleaned = re.sub(r"^\s*\d.+\s*$", "", cleaned)  # noop-ish
                if cleaned.strip():
                    text_lines.append(cleaned.strip())
        if not time_line or not text_lines:
            continue
        try:
            left, right = [p.strip() for p in time_line.split("-->")]
            right = right.split()[0]
            start = _vtt_ts(left)
            end = _vtt_ts(right)
        except Exception:
            continue
        body = " ".join(text_lines)
        if cues and cues[-1]["text"] == body and abs(cues[-1]["start"] - start) < 0.4:
            cues[-1]["end"] = end
            continue
        cues.append({"start": start, "end": end, "text": body, "source": "embedded_or_auto"})
    return cues


def _vtt_ts(s: str) -> float:
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    if len(parts) == 2:
        m, sec = parts
        return int(m) * 60 + float(sec)
    return float(s)


def collect_embedded_subs(subs: list[Path], dest_dir: Path) -> list[dict[str, Any]]:
    found = []
    for p in dest_dir.rglob("*.vtt"):
        found.append(p)
    for p in subs:
        if p not in found:
            found.append(p)
    # prefer zh, then en, skip empty
    def score(p: Path) -> int:
        n = p.name.lower()
        if "zh-hans" in n or "zh_cn" in n or n.endswith(".zh.vtt"):
            return 0
        if "zh" in n:
            return 1
        if re.search(r"(^|[.-])en([.-]|$)", n):
            return 2
        return 5
    found = [p for p in found if p.stat().st_size > 20]
    found.sort(key=score)
    if not found:
        return []
    return parse_vtt(found[0])


def load_wav_mono_f32(path: Path):
    """Load a PCM wav as float32 without PyAV (av 19 与 faster-whisper 的 metadata_errors 不兼容)."""
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        raise RuntimeError(f"只支持 16-bit PCM wav，实际 sampwidth={sw}")
    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)
    return audio, sr


def run_asr(wav: Path, model_name: str, model_dir: Path, language: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(model_dir))
    lang = None if not language or language == "auto" else language
    audio, sr = load_wav_mono_f32(wav)
    if sr != 16000:
        # should already be 16 kHz from ffmpeg; still pass the array
        pass
    segments, info = model.transcribe(audio, language=lang, vad_filter=True, beam_size=1)
    cues = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        cues.append({
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
            "source": f"faster-whisper:{model_name}",
        })
    meta = {
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "elapsed_sec": round(time.time() - t0, 2),
        "model": model_name,
        "device": "cpu",
        "compute_type": "int8",
    }
    return cues, meta


def run_ocr(frames_dir: Path, shots: list[dict[str, Any]]) -> dict[str, Any]:
    t0 = time.time()
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except Exception as e:
        return {"ok": False, "error": f"RapidOCR 未能加载：{e}", "elapsed_sec": 0}
    n_ok = 0
    for shot in shots:
        img = frames_dir / shot["keyframe"]
        if not img.exists():
            continue
        try:
            result, _elapse = ocr(str(img))
        except Exception as e:
            shot["ocr_text"] = ""
            shot["ocr_error"] = str(e)
            continue
        lines = []
        if result:
            for item in result:
                # item: [box, text, conf]
                try:
                    text = item[1]
                    conf = float(item[2])
                except Exception:
                    continue
                if text and conf >= 0.5:
                    lines.append(text.strip())
        shot["ocr_text"] = " / ".join(lines)
        if lines:
            n_ok += 1
    return {"ok": True, "frames_with_text": n_ok, "elapsed_sec": round(time.time() - t0, 2), "engine": "rapidocr-onnxruntime"}


def assign_speech(shots: list[dict[str, Any]], cues: list[dict[str, Any]], field: str) -> None:
    for shot in shots:
        pieces = []
        for c in cues:
            # overlap
            if c["end"] <= shot["start"] or c["start"] >= shot["end"]:
                continue
            pieces.append(c["text"])
        # dedup adjacent repeats
        cleaned = []
        for p in pieces:
            if not cleaned or cleaned[-1] != p:
                cleaned.append(p)
        shot[field] = " ".join(cleaned)


# -------------------- visuals / report --------------------

def _is_watermark_only(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    # common logo misreads of 「中新视频」plus bare 「视频」
    compact = t.replace(" ", "").replace("/", "")
    if compact in {"视频", "中新视频", "中利视频", "中州视频", "中洲视频", "中价视频", "中动视频", "中国视频", "中视频"}:
        return True
    return False


def featured_shots_for_report(shots: list[dict], limit: int = 8) -> list[dict]:
    """When speech is empty, prefer shots whose OCR carries real on-screen text."""
    if not shots:
        return []
    has_speech = any((s.get("speech") or s.get("embedded_sub") or "").strip() for s in shots)
    if has_speech:
        return shots[:limit]
    scored = []
    for s in shots:
        ocr = (s.get("ocr_text") or "").strip()
        if _is_watermark_only(ocr):
            continue
        scored.append((len(ocr), -s["index"], s))
    if not scored:
        return shots[:limit]
    picked = [s for _, __, s in sorted(scored, reverse=True)[:limit]]
    picked.sort(key=lambda s: s["index"])
    return picked


def wrap_text_full(text: str, font, max_width: int) -> list[str]:
    """Like wrap_text, but does not cap the number of lines (used for license footers)."""
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return []
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if font.getlength(trial) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_credit(img, text: str, margin: int = 16):
    """Paint a wrapped attribution footer. Returns image, possibly taller."""
    from PIL import Image, ImageDraw
    if not (text or "").strip():
        return img
    font = load_font(14)
    max_w = img.width - 2 * margin
    lines = wrap_text_full(text.strip(), font, max_w)
    line_h = 20
    need = 16 + line_h * len(lines) + 12
    # extend canvas if the last ~need pixels are not already reserved
    from PIL import Image as _Image
    new = _Image.new("RGB", (img.width, img.height + need), img.getpixel((0, 0)))
    new.paste(img, (0, 0))
    d = ImageDraw.Draw(new)
    y = img.height + 6
    for ln in lines:
        d.text((margin, y), ln, font=font, fill=(90, 90, 95) if new.getpixel((0, 0))[0] > 128 else (170, 174, 180))
        y += line_h
    return new


def load_font(size: int, bold: bool = False):

    from PIL import ImageFont
    path = FONT_BOLD if bold and Path(FONT_BOLD).exists() else FONT_REGULAR
    if Path(path).exists():
        return ImageFont.truetype(path, size=size, index=FONT_INDEX_SC)
    return ImageFont.load_default()


def wrap_text(text: str, font, max_width: int) -> list[str]:
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return []
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if font.getlength(trial) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines[:6]


def make_contact_sheet(shots: list[dict[str, Any]], frames_dir: Path, dest: Path, title: str, duration: float, credit: str = "") -> None:
    from PIL import Image, ImageDraw
    n = len(shots)
    cols = 4 if n > 4 else max(1, n)
    # vertical videos: fewer columns, taller cells
    first = frames_dir / shots[0]["keyframe"] if shots else None
    sample = Image.open(first) if first and first.exists() else None
    thumb_w = 280
    if sample:
        ratio = sample.height / max(sample.width, 1)
        if ratio > 1.2:
            cols = 3 if n > 3 else max(1, n)
            thumb_w = 220
    thumb_h = int(thumb_w * (sample.height / sample.width)) if sample else 160
    pad, header, caption_h = 16, 92, 78
    rows = math.ceil(n / cols) if n else 1
    W = pad + cols * (thumb_w + pad)
    H = header + rows * (thumb_h + caption_h + pad) + pad
    bg = (18, 18, 22)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    font_title = load_font(28, bold=True)
    font_sub = load_font(16)
    font_cap = load_font(14)
    font_sm = load_font(13)
    draw.text((pad, 16), "视频拆解 · 关键帧联系图", font=font_title, fill=(255, 255, 255))
    sub = f"{title}  ·  时长 {format_ts_short(duration)}  ·  {n} 个镜头  ·  用 Read 打开本图即可「看」画面"
    draw.text((pad, 54), sub[:120], font=font_sub, fill=(180, 186, 196))
    for i, shot in enumerate(shots):
        r, c = divmod(i, cols)
        x = pad + c * (thumb_w + pad)
        y = header + r * (thumb_h + caption_h + pad)
        fp = frames_dir / shot["keyframe"]
        if fp.exists():
            im = Image.open(fp).convert("RGB")
            im.thumbnail((thumb_w, thumb_h))
            # letterbox
            cell = Image.new("RGB", (thumb_w, thumb_h), (8, 8, 10))
            ox = (thumb_w - im.width) // 2
            oy = (thumb_h - im.height) // 2
            cell.paste(im, (ox, oy))
            img.paste(cell, (x, y))
        else:
            draw.rectangle([x, y, x + thumb_w, y + thumb_h], fill=(40, 40, 48))
        # badge
        badge = f"#{i+1}  {format_ts_short(shot['start'])}–{format_ts_short(shot['end'])}  ({shot['duration']:.1f}s)"
        draw.rectangle([x, y, x + thumb_w, y + 22], fill=(0, 0, 0))
        draw.text((x + 6, y + 3), badge, font=font_sm, fill=(255, 220, 80))
        cap = shot.get("ocr_text") or shot.get("speech") or shot.get("embedded_sub") or ""
        cap = cap.replace("\n", " ")
        lines = wrap_text(cap, font_cap, thumb_w - 8)
        ty = y + thumb_h + 4
        if not lines:
            draw.text((x, ty), "（本镜无明显字幕/口播）", font=font_cap, fill=(120, 124, 132))
        for ln in lines[:3]:
            draw.text((x, ty), ln, font=font_cap, fill=(230, 232, 236))
            ty += 18
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = draw_credit(img, credit, margin=pad)
    img.save(dest, "PNG", optimize=True)


def make_timeline(shots: list[dict[str, Any]], frames_dir: Path, dest: Path, title: str, duration: float, pacing: dict[str, Any], credit: str = "") -> None:
    from PIL import Image, ImageDraw
    W, H = 1600, 720
    bg = (16, 17, 22)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    font_title = load_font(30, bold=True)
    font = load_font(18)
    font_sm = load_font(14)
    draw.text((28, 18), "视频拆解 · 分镜时间轴", font=font_title, fill=(255, 255, 255))
    pace = (
        f"{title}    时长 {format_ts_short(duration)}    "
        f"{pacing.get('shot_count', 0)} 镜    "
        f"平均镜头 {pacing.get('avg_shot_sec', 0):.1f}s    "
        f"中位 {pacing.get('median_shot_sec', 0):.1f}s    "
        f"每分钟切 {pacing.get('cuts_per_minute', 0):.1f} 次"
    )
    draw.text((28, 58), pace[:140], font=font, fill=(180, 186, 196))

    # thumbnail strip
    n = len(shots) or 1
    margin, top = 28, 110
    usable = W - 2 * margin
    # pick thumbnails (all if few, else evenly)
    show = shots if len(shots) <= 10 else [shots[i] for i in _evenly_pick(list(range(len(shots))), 10)]
    # _evenly_pick on indices needs list of numbers treated as times — reuse simple pick
    if len(shots) > 10:
        idxs = [0] + [round(i * (n - 1) / 9) for i in range(1, 10)]
        idxs = sorted(set(idxs))
        show = [shots[i] for i in idxs]
    tw = min(140, usable // max(len(show), 1) - 8)
    # height from first frame
    first_fp = frames_dir / shots[0]["keyframe"] if shots else None
    ratio = 9 / 16
    if first_fp and first_fp.exists():
        im0 = Image.open(first_fp)
        ratio = im0.height / max(im0.width, 1)
    th = int(tw * min(ratio, 1.7))
    x = margin
    for shot in show:
        fp = frames_dir / shot["keyframe"]
        if fp.exists():
            im = Image.open(fp).convert("RGB")
            im.thumbnail((tw, th))
            cell = Image.new("RGB", (tw, th), (8, 8, 10))
            cell.paste(im, ((tw - im.width) // 2, (th - im.height) // 2))
            img.paste(cell, (x, top))
        draw.text((x, top + th + 4), f"#{shot['index']+1} {format_ts_short(shot['start'])}", font=font_sm, fill=(255, 220, 80))
        x += tw + 12

    # timeline bar
    bar_y = top + th + 50
    bar_h = 36
    draw.rounded_rectangle([margin, bar_y, margin + usable, bar_y + bar_h], radius=6, fill=(36, 38, 48))
    colors = [(80, 160, 255), (255, 170, 70), (120, 210, 150), (230, 110, 140), (180, 150, 255)]
    for i, shot in enumerate(shots):
        if duration <= 0:
            continue
        x0 = margin + usable * (shot["start"] / duration)
        x1 = margin + usable * (shot["end"] / duration)
        if x1 - x0 < 2:
            x1 = x0 + 2
        color = colors[i % len(colors)]
        draw.rectangle([x0, bar_y, x1 - 1, bar_y + bar_h], fill=color)
    # time ticks
    ticks = 6
    for i in range(ticks + 1):
        t = duration * i / ticks
        tx = margin + usable * (i / ticks)
        draw.line([tx, bar_y + bar_h, tx, bar_y + bar_h + 8], fill=(140, 144, 155), width=1)
        draw.text((tx - 12, bar_y + bar_h + 10), format_ts_short(t), font=font_sm, fill=(140, 144, 155))

    # subtitle track (up to ~8 cues worth of speech)
    sub_y = bar_y + bar_h + 48
    draw.text((margin, sub_y), "口播 / 字幕轨道（按镜头）", font=font, fill=(230, 232, 236))
    y = sub_y + 32
    font_body = load_font(16)
    for shot in shots:
        if y > H - 40:
            draw.text((margin, H - 28), "……其余镜头见报告正文", font=font_sm, fill=(140, 144, 155))
            break
        text = shot.get("speech") or shot.get("embedded_sub") or shot.get("ocr_text") or "（无）"
        line = f"{format_ts_short(shot['start'])}  {text}"
        wrapped = wrap_text(line, font_body, usable)
        for ln in wrapped[:2]:
            if y > H - 36:
                break
            draw.text((margin, y), ln, font=font_body, fill=(210, 214, 220))
            y += 22
        y += 4
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = draw_credit(img, credit, margin=28)
    img.save(dest, "PNG", optimize=True)


def make_report_png(report: dict[str, Any], shots: list[dict[str, Any]], frames_dir: Path, dest: Path, contact: Path, timeline: Path, credit: str = "", featured: list[dict[str, Any]] | None = None) -> None:
    """One-page Chinese report sample (PNG), for delivery visual."""
    from PIL import Image, ImageDraw
    W, H = 1400, 2000
    bg = (248, 247, 243)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    font_h1 = load_font(36, bold=True)
    font_h2 = load_font(24, bold=True)
    font = load_font(18)
    font_sm = load_font(15)
    ink, muted, accent = (28, 28, 30), (90, 90, 95), (180, 60, 40)
    y = 36
    draw.text((48, y), "公开视频拆解报告（样例）", font=font_h1, fill=ink)
    y += 56
    src = report.get("source") or {}
    head_lines = [
        f"标题：{src.get('title') or '（未命名）'}",
        f"来源：{src.get('platform')}    链接：{(src.get('url') or src.get('source_file') or '本机文件')[:90]}",
        f"时长：{format_ts_short(report.get('duration_sec') or 0)}    画幅：{src.get('width')}×{src.get('height')} ({src.get('orientation')})",
        f"镜头数：{(report.get('pacing') or {}).get('shot_count')}    平均镜头 {(report.get('pacing') or {}).get('avg_shot_sec')} 秒    每分钟切换 {(report.get('pacing') or {}).get('cuts_per_minute')} 次",
        f"字幕来源：{report.get('subtitle_source') or '无内嵌字幕，使用 CPU Whisper 口播转写'}",
    ]
    for ln in head_lines:
        draw.text((48, y), ln[:110], font=font, fill=ink)
        y += 30
    y += 8
    draw.line([48, y, W - 48, y], fill=(200, 198, 190), width=1)
    y += 16
    # paste timeline scaled
    if timeline.exists():
        tim = Image.open(timeline).convert("RGB")
        tw = W - 96
        th = int(tim.height * tw / tim.width)
        tim = tim.resize((tw, th), Image.Resampling.LANCZOS)
        # crop if too tall
        max_h = 420
        if th > max_h:
            tim = tim.crop((0, 0, tw, max_h))
            th = max_h
        img.paste(tim, (48, y))
        y += th + 20
    shown = featured if featured is not None else featured_shots_for_report(shots, 8)
    empty_speech = not any((s.get("speech") or s.get("embedded_sub") or "").strip() for s in shots)
    if empty_speech:
        banner = "口播转写为空。下面优先列出画面硬字幕（OCR）读到的关键信息，而不是听写稿。"
        draw.text((48, y), banner, font=font, fill=accent)
        y += 32
    draw.text((48, y), "分镜表（硬字幕信息镜）" if empty_speech else "分镜表（前若干镜）", font=font_h2, fill=ink)
    y += 40
    # table-like rows
    for shot in shown:
        fp = frames_dir / shot["keyframe"]
        row_h = 118
        if y + row_h > H - 80:
            break
        if fp.exists():
            im = Image.open(fp).convert("RGB")
            im.thumbnail((90, 110))
            img.paste(im, (48, y))
        draw.text((150, y), f"#{shot['index']+1}  {format_ts_short(shot['start'])}–{format_ts_short(shot['end'])}  镜头 {shot['duration']:.1f}s", font=font, fill=accent)
        body = shot.get("speech") or shot.get("embedded_sub") or ""
        ocr = shot.get("ocr_text") or ""
        desc = shot.get("visual_description") or ""
        lines = []
        if body:
            lines.append("口播：" + body)
        if ocr:
            lines.append("画面字：" + ocr)
        if desc and not desc.startswith("【待"):
            lines.append("画面：" + desc)
        if not lines:
            lines.append("（本镜暂无口播/OCR）")
        ty = y + 26
        for ln in lines:
            for wrapped in wrap_text(ln, font_sm, W - 220)[:3]:
                draw.text((150, ty), wrapped, font=font_sm, fill=ink)
                ty += 22
        y += row_h
    y += 8
    notes = report.get("limitations") or []
    if notes:
        draw.text((48, min(y, H - 160)), "局限与失败点（如实记录）", font=font_h2, fill=ink)
        y = min(y + 36, H - 130)
        for n in notes[:5]:
            for ln in wrap_text("· " + n, font_sm, W - 100)[:3]:
                if y > H - 40:
                    break
                draw.text((48, y), ln, font=font_sm, fill=muted)
                y += 22
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = draw_credit(img, credit, margin=48)
    img.save(dest, "PNG", optimize=True)


def write_markdown(report: dict[str, Any], dest: Path) -> None:
    src = report.get("source") or {}
    pacing = report.get("pacing") or {}
    lines = [
        f"# 视频拆解报告：{src.get('title') or '未命名'}",
        "",
        *_attribution_md_lines(src),
        f"- 来源平台：{src.get('platform')}",
        f"- 链接：{src.get('url') or src.get('source_file') or '本机文件'}",
        f"- 时长：{report.get('duration_sec')} 秒（{format_ts_short(report.get('duration_sec') or 0)}）",
        f"- 画幅：{src.get('width')}×{src.get('height')}（{src.get('orientation')}）",
        f"- 字幕来源：{report.get('subtitle_source')}",
        f"- 镜头数：{pacing.get('shot_count')}；平均 {pacing.get('avg_shot_sec')} 秒/镜；中位 {pacing.get('median_shot_sec')} 秒；每分钟切换 {pacing.get('cuts_per_minute')} 次",
        "",
        "## 如何「看」这支视频",
        "",
        "1. 用带图像能力的模型 / 工具打开同目录的 `contact_sheet.png`（关键帧联系图）和 `timeline.png`（分镜时间轴）。",
        "2. 在支持读图的 agent 环境里，对图片路径调用 **Read** 工具，即可直接看见画面。",
        "3. 按下面分镜表的时间码，把每格的画面描述写回 `visual_description` 字段（脚本只放占位，不编造画面）。",
        "",
        "## 镜头节奏",
        "",
        f"- 最短镜头 {pacing.get('shortest_sec')} 秒，最长 {pacing.get('longest_sec')} 秒。",
        f"- 切点判定：{report.get('cut_mode')}（场景变化阈值 {report.get('scene_threshold')}）。",
        "",
        "## 分镜表",
        "",
        "| # | 时间 | 时长 | 关键帧 | 口播/字幕 | 画面字（OCR） | 画面描述 |",
        "|---|------|------|--------|-----------|---------------|----------|",
    ]
    for s in report.get("shots") or []:
        speech = (s.get("speech") or s.get("embedded_sub") or "").replace("|", "\\|").replace("\n", " ")
        ocr = (s.get("ocr_text") or "").replace("|", "\\|")
        desc = (s.get("visual_description") or "").replace("|", "\\|")
        lines.append(
            f"| {s['index']+1} | {format_ts_short(s['start'])}–{format_ts_short(s['end'])} | {s['duration']:.1f}s | {s['keyframe']} | {speech} | {ocr} | {desc} |"
        )
    lines += [
        "",
        "## 完整口播 / 字幕",
        "",
    ]
    for c in report.get("transcript") or []:
        lines.append(f"- {format_ts_short(c['start'])}–{format_ts_short(c['end'])}  {c['text']}")
    if not report.get("transcript"):
        lines.append("（无）")
    lines += ["", "## 局限", ""]
    for n in report.get("limitations") or []:
        lines.append(f"- {n}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(report: dict[str, Any], dest: Path, contact_name: str, timeline_name: str, frames_rel: str) -> None:
    src = report.get("source") or {}
    pacing = report.get("pacing") or {}
    rows = []
    for s in report.get("shots") or []:
        rows.append(
            "<tr>"
            f"<td>{s['index']+1}</td>"
            f"<td>{format_ts_short(s['start'])}–{format_ts_short(s['end'])}<br><small>{s['duration']:.1f}s</small></td>"
            f"<td><img src='{frames_rel}/{s['keyframe']}' alt='shot {s['index']+1}' style='max-width:120px;height:auto;border-radius:4px'/></td>"
            f"<td>{_html(s.get('speech') or s.get('embedded_sub') or '')}</td>"
            f"<td>{_html(s.get('ocr_text') or '')}</td>"
            f"<td>{_html(s.get('visual_description') or '')}</td>"
            "</tr>"
        )
    cues = "".join(
        f"<li><code>{format_ts_short(c['start'])}</code> {_html(c['text'])}</li>"
        for c in (report.get("transcript") or [])
    ) or "<li>（无）</li>"
    limits = "".join(f"<li>{_html(n)}</li>" for n in (report.get("limitations") or []))
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>视频拆解报告 — {_html(src.get('title') or '')}</title>
<style>
  body {{ font-family: "Noto Sans CJK SC", "Noto Sans CJK SC Regular", "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
         background:#f7f6f2; color:#1c1c1e; margin:0; padding:24px; line-height:1.55; }}
  main {{ max-width: 1080px; margin:0 auto; background:white; padding:32px; border-radius:12px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
  h1 {{ font-size:28px; margin:0 0 8px; }}
  .meta {{ color:#555; }}
  img.wide {{ width:100%; height:auto; border-radius:8px; margin:12px 0 24px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th,td {{ border:1px solid #e6e3dc; padding:8px 10px; vertical-align:top; }}
  th {{ background:#f3f0ea; text-align:left; }}
  code {{ background:#f3f0ea; padding:1px 4px; border-radius:3px; }}
</style>
</head>
<body>
<main>
<h1>视频拆解报告</h1>
<p class="meta">
标题：{_html(src.get('title') or '未命名')}<br/>
来源：{_html(src.get('platform') or '')} · {_html(src.get('url') or src.get('source_file') or '本机文件')}<br/>
时长 {format_ts_short(report.get('duration_sec') or 0)} · 画幅 {src.get('width')}×{src.get('height')}（{src.get('orientation')}）<br/>
{pacing.get('shot_count')} 镜 · 平均 {pacing.get('avg_shot_sec')} 秒/镜 · 每分钟切换 {pacing.get('cuts_per_minute')} 次<br/>
字幕来源：{_html(report.get('subtitle_source') or '')}{_attribution_html(src)}
</p>
<h2>分镜时间轴</h2>
<img class="wide" src="{_html(timeline_name)}" alt="分镜时间轴"/>
<h2>关键帧联系图（给多模态模型看）</h2>
<p>在支持读图的环境中，用 Read 工具打开 <code>contact_sheet.png</code>，即可按时间码对照画面。不要在未看图时编造画面描述。</p>
<img class="wide" src="{_html(contact_name)}" alt="关键帧联系图"/>
<h2>分镜表</h2>
<table>
<thead><tr><th>#</th><th>时间</th><th>关键帧</th><th>口播/字幕</th><th>画面字（OCR）</th><th>画面描述</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<h2>完整口播 / 字幕</h2>
<ol>{cues}</ol>
<h2>局限与失败点</h2>
<ul>{limits}</ul>
</main>
</body>
</html>
"""
    dest.write_text(html, encoding="utf-8")


def _html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def _parse_attribution(credit: str, url: str | None, uploader: str | None) -> dict[str, str]:
    """Pull author / license / license_url out of --credit and the source URL when present."""
    info: dict[str, str] = {}
    if uploader:
        info["author"] = str(uploader)
    text = (credit or "").strip()
    if text:
        m = re.search(
            r"CC\s+BY(?:-(?:SA|NC|ND|NC-SA|NC-ND))?\s*\d(?:\.\d+)?",
            text,
            re.I,
        )
        if m:
            lic = re.sub(r"\s+", " ", m.group(0).upper())
            lic = lic.replace("BY-SA", "BY-SA").replace("BY-NC-SA", "BY-NC-SA")
            # Keep the well-known hyphenated tokens; only space-normalize.
            info["license"] = lic.replace("CC BY- ", "CC BY-")
        u = re.search(r"https://creativecommons.org/licenses/[^\s）)\]>,，]+", text)
        if u:
            info["license_url"] = u.group(0).rstrip("。.,；;")
        if "author" not in info:
            head = re.sub(r"^素材[：:]\s*", "", text)
            head = re.split(r"[《，,：:]", head, maxsplit=1)[0].strip()
            if head and "CC " not in head.upper() and "http" not in head.lower() and 1 <= len(head) <= 40:
                info["author"] = head
    return info


def _attribution_md_lines(src: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    author = src.get("author") or src.get("uploader")
    license_name = src.get("license")
    license_url = src.get("license_url")
    credit = (src.get("credit") or "").strip()
    url = src.get("url") or ""
    if author:
        lines.append(f"- 作者：{author}")
    if license_name and license_url:
        lines.append(f"- 许可：{license_name}（{license_url} ）")
    elif license_name:
        lines.append(f"- 许可：{license_name}")
    elif license_url:
        lines.append(f"- 许可：{license_url}")
    if url and "commons.wikimedia.org" in url:
        lines.append(f"- Commons 页面：{url}")
    if license_name or license_url or credit:
        lines.append("- 本报告含原片关键帧截图，已按许可署名；仅用于学习分析自己有权查看的视频。")
        if credit and not license_name:
            lines.append(f"- 署名与许可：{credit}")
    return lines


def _attribution_html(src: dict[str, Any]) -> str:
    parts: list[str] = []
    author = src.get("author") or src.get("uploader")
    license_name = src.get("license")
    license_url = src.get("license_url")
    credit = (src.get("credit") or "").strip()
    url = src.get("url") or ""
    if author:
        parts.append(f"作者：{_html(author)}")
    if license_name and license_url:
        parts.append(f"许可：{_html(license_name)}（{_html(license_url)}）")
    elif license_name:
        parts.append(f"许可：{_html(license_name)}")
    elif license_url:
        parts.append(f"许可：{_html(license_url)}")
    if url and "commons.wikimedia.org" in url:
        parts.append(f"Commons 页面：{_html(url)}")
    if license_name or license_url or credit:
        parts.append("本报告含原片关键帧截图，已按许可署名；仅用于学习分析自己有权查看的视频。")
        if credit and not license_name:
            parts.append(f"署名与许可：{_html(credit)}")
    if not parts:
        return ""
    return "<br/>\n" + "<br/>\n".join(parts) + "\n"




# -------------------- main pipeline --------------------

def process(args: argparse.Namespace) -> Path:
    t_all = time.time()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    limitations: list[str] = []
    model_dir = Path(args.model_dir).expanduser().resolve()
    model_dir.mkdir(parents=True, exist_ok=True)

    # 1. acquire
    t0 = time.time()
    acquired = acquire(args.input, out / "_source", args.max_duration, args.max_filesize, args.mode, cookies=(args.cookies or None), requested_downloader=(None if args.downloader == "auto" else args.downloader))
    media: Path = acquired["media"]
    meta = acquired["meta"]
    if args.source_url and not meta.get("url"):
        meta["url"] = args.source_url
        meta["platform"] = guess_platform(args.source_url)
    info = ffprobe_info(media)
    if not info.get("vcodec") and info["duration"] <= 0:
        raise SystemExit(f"无法读取该文件，可能已损坏或不是音视频：{media}")
    if info["duration"] > args.max_duration + 1:
        # trim local copy
        trimmed = out / f"trimmed{media.suffix}"
        run([
            which_or_die("ffmpeg"), "-y", "-i", str(media),
            "-t", str(args.max_duration), "-c", "copy", str(trimmed),
        ], timeout=60)
        media = trimmed
        info = ffprobe_info(media)
        limitations.append(f"原片超过 {args.max_duration} 秒，已按上限截取前段。")
    acquire_sec = round(time.time() - t0, 2)
    if info["duration"] <= 0:
        raise SystemExit("无法读取视频时长，文件可能损坏或不是音视频。")

    # 2. scenes + frames
    t0 = time.time()
    times = detect_scene_times(media, args.scene_threshold, info["duration"])
    times, cut_mode = maybe_interval_sample(times, info["duration"], args.interval, args.max_shots)
    shots = build_shots(times, cut_mode, frames_dir, media, args.max_shots)
    pacing = pacing_stats(shots, info["duration"])
    scene_sec = round(time.time() - t0, 2)

    # 3. captions then ASR
    t0 = time.time()
    embedded = collect_embedded_subs(acquired.get("subs") or [], out / "_source")
    subtitle_source = ""
    transcript: list[dict[str, Any]] = []
    asr_meta: dict[str, Any] = {}
    if embedded and not args.force_asr:
        transcript = embedded
        subtitle_source = "内嵌或平台自动字幕（VTT）"
        assign_speech(shots, transcript, "embedded_sub")
        assign_speech(shots, transcript, "speech")
    else:
        if embedded:
            limitations.append("虽然检测到内嵌字幕，但按 --force-asr 仍跑了 Whisper，内嵌稿另存对照。")
        has_audio = bool(info.get("acodec"))
        wav = out / "audio.wav"
        extracted = False
        if not has_audio:
            limitations.append("该文件没有音轨，已跳过口播转写；分镜图和 OCR 仍会生成。")
            subtitle_source = "无音轨，已跳过口播转写"
        else:
            extracted = extract_audio(media, wav)
            if not extracted:
                limitations.append("无法抽出可用音轨，已跳过口播转写；分镜图和 OCR 仍会生成。")
                subtitle_source = "无可用音轨，已跳过口播转写"
        if extracted:
            try:
                transcript, asr_meta = run_asr(wav, args.whisper_model, model_dir, args.language)
                subtitle_source = f"无可用内嵌字幕，已用 CPU faster-whisper {args.whisper_model}（int8）转写口播"
                if not transcript:
                    limitations.append("Whisper 未转写出任何口播（可能是纯音乐/环境音，或音轨极轻）。")
                    subtitle_source += "；本片转写为空"
                assign_speech(shots, transcript, "speech")
            except Exception as e:
                limitations.append(f"Whisper 转写失败：{e}")
                subtitle_source = "口播转写失败"
    asr_sec = round(time.time() - t0, 2)

    # 4. OCR
    t0 = time.time()
    ocr_meta: dict[str, Any] = {}
    if args.skip_ocr:
        limitations.append("按参数跳过了 OCR。")
    else:
        ocr_meta = run_ocr(frames_dir, shots)
        if not ocr_meta.get("ok"):
            limitations.append(ocr_meta.get("error") or "OCR 失败")
        elif ocr_meta.get("frames_with_text", 0) == 0:
            limitations.append("OCR 没有在关键帧上读到足够自信的文字（硬字幕可能太小、被压缩，或本片没有烧录字幕）。")
    ocr_sec = round(time.time() - t0, 2)

    limitations.append("画面描述需由带图像能力的模型查看 contact_sheet.png 后填写，脚本本身不编造画面。")
    limitations.append("ASR / OCR 会有错字，报告里的口播和画面字不能当成逐字稿使用，需对照原片或联系图抽查。")

    source = {
        "url": meta.get("url") or args.source_url,
        "source_file": meta.get("source_file"),
        "platform": meta.get("platform"),
        "title": args.title or _clean_title(meta.get("title")) or media.stem,
        "uploader": meta.get("uploader"),
        "credit": args.credit or "",
        "downloader": meta.get("downloader"),
        "tried_downloaders": meta.get("tried_downloaders"),
        "cookies_provided": bool(args.cookies),
        "width": info["width"],
        "height": info["height"],
        "orientation": info["orientation"],
        "vcodec": info["vcodec"],
        "acodec": info["acodec"],
        "search_query": meta.get("search_query"),
    }
    attrib = _parse_attribution(source["credit"], source.get("url"), source.get("uploader"))
    if attrib.get("author"):
        source["author"] = attrib["author"]
    if attrib.get("license"):
        source["license"] = attrib["license"]
    if attrib.get("license_url"):
        source["license_url"] = attrib["license_url"]
    report = {
        "source": source,
        "duration_sec": round(info["duration"], 3),
        "pacing": pacing,
        "cut_mode": cut_mode,
        "scene_threshold": args.scene_threshold,
        "subtitle_source": subtitle_source,
        "shots": shots,
        "transcript": transcript,
        "embedded_subs_detected": bool(embedded),
        "asr": asr_meta,
        "ocr": ocr_meta,
        "timings_sec": {
            "acquire": acquire_sec,
            "scenes_frames": scene_sec,
            "asr_or_subs": asr_sec,
            "ocr": ocr_sec,
            "total": None,
        },
        "limitations": limitations,
        "how_to_see_frames": {
            "contact_sheet": "contact_sheet.png",
            "timeline": "timeline.png",
            "instruction": "在支持读图的 agent 中对上述 PNG 调用 Read 工具；或把 HTML 报告在浏览器里打开。看图后再填写 visual_description，禁止未看图脑补。",
        },
    }

    # 5. visuals
    t0 = time.time()
    contact = out / "contact_sheet.png"
    timeline = out / "timeline.png"
    report_png = out / "report_page.png"
    credit = args.credit or ""
    make_contact_sheet(shots, frames_dir, contact, source["title"], info["duration"], credit=credit)
    make_timeline(shots, frames_dir, timeline, source["title"], info["duration"], pacing, credit=credit)
    make_report_png(report, shots, frames_dir, report_png, contact, timeline, credit=credit)
    write_markdown(report, out / "report.md")
    write_html(report, out / "report.html", "contact_sheet.png", "timeline.png", "frames")
    report["timings_sec"]["visuals"] = round(time.time() - t0, 2)
    report["timings_sec"]["total"] = round(time.time() - t_all, 2)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="把公开或用户提供的视频拆成可被任意 agent「看」懂的分镜报告（纯 CPU）")
    p.add_argument("input", nargs="?", default="", help="公开链接、本地文件、inbox 目录，或（配合 --search）关键词")
    p.add_argument("--mode", choices=["auto", "url", "file", "search"], default="auto")
    p.add_argument("--search", action="store_true", help="把 input 当作 YouTube 搜索词（ytsearch1）")
    p.add_argument("--file", dest="as_file", action="store_true", help="把 input 当作本地文件")
    p.add_argument(
        "--auto",
        dest="auto_flag",
        action="store_true",
        help="自动判断档 1/2/3：尝试下载，失败则使用 inbox/ 里的视频或 cookies.txt，再否则给出最短手动步骤和 JSON 状态",
    )
    p.add_argument("--inbox", default="", help="用户放置视频或 cookies.txt 的文件夹，默认包内 inbox/")
    p.add_argument("--out", default="", help="输出目录；省略时为包内 out/auto")
    p.add_argument("--title", default="", help="覆盖标题")
    p.add_argument("--source-url", default="", help="本地文件对应的原始公开链接，仅用于引用")
    p.add_argument("--max-duration", type=int, default=DEFAULT_MAX_DURATION, help="最长处理秒数，默认 300")
    p.add_argument("--max-filesize", type=int, default=DEFAULT_MAX_FILESIZE, help="下载体积上限（字节）")
    p.add_argument("--scene-threshold", type=float, default=DEFAULT_SCENE_TH)
    p.add_argument("--interval", type=float, default=INTERVAL_FALLBACK, help="场景切分过少时的补采样间隔（秒）")
    p.add_argument("--max-shots", type=int, default=DEFAULT_MAX_SHOTS)
    p.add_argument("--whisper-model", default="base", help="tiny / base / small（CPU 建议 base）")
    p.add_argument("--model-dir", default=str(Path(__file__).resolve().parent.parent / "models"))
    p.add_argument("--language", default="auto", help="auto / zh / en ...")
    p.add_argument("--force-asr", action="store_true", help="即使有内嵌字幕也跑 Whisper")
    p.add_argument("--skip-ocr", action="store_true")
    p.add_argument("--credit", default="", help="写在联系图/时间轴/报告页底部的署名与许可")
    p.add_argument(
        "--cookies",
        default="",
        help="你自行导出并放置的 Netscape 格式 cookie 文件路径。本工具不代取，也不从浏览器读取。",
    )
    p.add_argument(
        "--downloader",
        default="auto",
        choices=["auto", "yt-dlp", "yutto", "bbdown", "you-get"],
        help="下载器选择。默认 auto：按链接选（yt-dlp 优先；B 站可回退到已安装的 yutto/BBDown/you-get）。抖音/小红书只尝试 yt-dlp。",
    )
    return p


def _emit(status: dict, out_dir: Path | None, *, human: str | None = None, code: int | None = None) -> None:
    if human:
        print(human, file=sys.stdout if status.get("status") == "ok" else sys.stderr)
    print(proto.STATUS_MARKER)
    print(proto.emit_status(status, out_dir))
    if code is not None:
        sys.exit(code)


def prepare_auto(args: argparse.Namespace) -> None:
    """Resolve --auto / inbox / default --out before the pipeline runs."""
    inbox = proto.ensure_inbox(Path(args.inbox).expanduser() if args.inbox else proto.default_inbox())
    args.inbox_path = inbox
    args.cookies_from_inbox = False
    args.tier_hint = 2 if (args.as_file or args.mode == "file") else 1
    args.empty_inbox = False
    if not args.out:
        args.out = str(proto.default_out())
    if not args.cookies:
        found = proto.find_inbox_cookies(inbox)
        if found:
            args.cookies = str(found)
            args.cookies_from_inbox = True
    raw = (args.input or "").strip()
    # --auto (or a bare "inbox" argument) should never fall through to YouTube search.
    treat_auto = bool(args.auto_flag) or raw.lower() in {"inbox", "inbox/"} or (
        raw and Path(raw).expanduser().is_dir() and proto.find_inbox_video(Path(raw).expanduser())
    )
    if not treat_auto and not raw:
        # no input at all: if --auto was forgotten but inbox has a file, still accept with --auto only
        return
    if args.auto_flag or raw.lower() in {"inbox", "inbox/"}:
        if not raw or raw.lower() in {"inbox", "inbox/"}:
            video = proto.find_inbox_video(inbox)
            if video:
                args.input = str(video)
                args.mode = "file"
                args.as_file = True
                args.tier_hint = 2
                return
            args.empty_inbox = True
            args.input = str(inbox)
            return
        if proto.looks_like_url(raw):
            args.mode = "url"
            args.tier_hint = 1
            return
        path = Path(raw).expanduser()
        if path.is_file():
            args.input = str(path)
            args.mode = "file"
            args.as_file = True
            args.tier_hint = 2
            return
        if path.is_dir():
            args.inbox_path = path
            if not args.cookies:
                found = proto.find_inbox_cookies(path)
                if found:
                    args.cookies = str(found)
                    args.cookies_from_inbox = True
            video = proto.find_inbox_video(path)
            if video:
                args.input = str(video)
                args.mode = "file"
                args.as_file = True
                args.tier_hint = 2
                return
            args.empty_inbox = True
            return
        # Unknown non-URL text with --auto: do not silently YouTube-search.
        if not args.search:
            args.unrecognized = raw
            return


def _need_user_status(args: argparse.Namespace, kind: str, err_text: str, url: str | None) -> dict:
    inbox: Path = getattr(args, "inbox_path", proto.default_inbox())
    out_dir = Path(args.out).expanduser() if args.out else proto.default_out()
    platform = guess_platform(url) if url else guess_platform(args.source_url or None)
    reason = proto.normalize_reason(kind)
    secrets = proto.cookie_secret_values(Path(args.cookies).expanduser()) if args.cookies else []
    label = proto.platform_label(platform)
    if kind in {"cookies", "need_cookies"}:
        message = f"未能自动取到这条「{label}」链接：下载器提示需要 cookie。我不会代取，也不会读取你的浏览器。"
    elif kind == "login":
        message = f"未能自动取到这条「{label}」链接：未登录时无法访问（例如跳到了登录页）。"
    elif kind == "waf":
        message = f"未能自动取到这条「{label}」链接：平台或中间层拒绝了请求（常见 HTTP 412 / 风控）。不一定是链接无效。"
    elif kind == "ratelimit":
        message = f"未能自动取到这条「{label}」链接：请求过于频繁或被判定为机器人（常见 HTTP 429）。"
    elif kind == "geo":
        message = f"这条「{label}」内容有地区限制，当前网络环境取不到。"
    elif kind == "restricted":
        message = f"这条「{label}」内容可能需要会员、付费或受 DRM 保护。本工具不会绕过这类限制。"
    elif kind == "no_media":
        message = "收件夹里还没有视频文件，也没有可下载的公开链接。"
    elif kind == "unsupported":
        message = f"未能自动取到这条「{label}」链接：所用下载器不支持这条链接，或页面无法解析。"
    else:
        message = f"未能自动取到这条「{label}」链接。"
    if err_text:
        message += "\n" + proto.redact_text(err_text.strip()[:400], secrets)
    if getattr(args, "cookies_from_inbox", False) or args.cookies:
        message += "\n已使用你放在 inbox/ 或 --cookies 指向的 cookie 文件重试过，仍然失败。用真实登录态是否有效，本包未实测。"
    steps = proto.user_steps(
        platform=platform or "other",
        url=url,
        inbox=inbox,
        out_dir=out_dir,
        reason=reason,
    )
    return proto.build_status(
        status="need_user",
        tier=2,
        reason_code=reason,
        message=message,
        platform=platform,
        url=url,
        out_dir=out_dir,
        inbox=inbox,
        user_steps_list=steps,
        secrets=secrets,
        extras={"tried_cookies": bool(args.cookies)},
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.unrecognized = None
    if args.search:
        args.mode = "search"
    if args.as_file:
        args.mode = "file"
    prepare_auto(args)
    out_dir = Path(args.out).expanduser() if args.out else proto.default_out()
    inbox: Path = getattr(args, "inbox_path", proto.default_inbox())
    url = args.input if proto.looks_like_url(args.input or "") else (args.source_url or None)

    if getattr(args, "unrecognized", None):
        status = proto.build_status(
            status="failed",
            tier=3,
            reason_code="other",
            message=(
                f"无法识别输入：{args.unrecognized}\n"
                f"请给一个链接、一个视频文件，或先把文件放进 {inbox} 再运行 --auto inbox。"
            ),
            out_dir=out_dir,
            inbox=inbox,
        )
        _emit(status, out_dir, human=proto.format_human(status), code=2)

    if getattr(args, "empty_inbox", False) and not url:
        status = _need_user_status(args, "no_media", "", None)
        _emit(status, out_dir, human=proto.format_human(status), code=2)

    if not (args.input or "").strip() and not args.search:
        parser.error("请提供链接、本地文件，或使用 --auto inbox（先把文件放进 inbox/）。")

    original_url = url
    try:
        out = process(args)
    except RuntimeError as e:
        raw = e.raw if isinstance(e, DownloadFailed) else str(e)
        kind = e.kind if isinstance(e, DownloadFailed) else classify_download_error(raw)
        video = proto.find_inbox_video(inbox)
        if video and args.mode != "file":
            args.input = str(video)
            args.mode = "file"
            args.as_file = True
            args.tier_hint = 2
            if original_url and not args.source_url:
                args.source_url = original_url
            try:
                out = process(args)
                args._used_inbox_fallback = True
            except (RuntimeError, subprocess.CalledProcessError, SystemExit):
                status = _need_user_status(args, kind, raw, original_url)
                _emit(status, out_dir, human=proto.format_human(status), code=2)
        else:
            status = _need_user_status(args, kind, raw, original_url)
            _emit(status, out_dir, human=proto.format_human(status), code=2)
    except SystemExit as e:
        # Missing tools / missing cookie file, already printed.
        msg = e.args[0] if e.args else str(e)
        if isinstance(msg, int):
            raise
        secrets = proto.cookie_secret_values(Path(args.cookies).expanduser()) if args.cookies else []
        text = proto.redact_text(str(msg), secrets)
        is_corrupt = "无法读取该文件" in text or "损坏" in text
        status = proto.build_status(
            status="failed",
            tier=3,
            reason_code="corrupt" if is_corrupt else "other",
            message=text,
            platform=guess_platform(original_url) if original_url else None,
            url=original_url,
            out_dir=out_dir,
            inbox=inbox,
            secrets=secrets,
        )
        _emit(status, out_dir, human=proto.format_human(status), code=1 if is_corrupt else 2)
    except subprocess.CalledProcessError:
        status = proto.build_status(
            status="failed",
            tier=3,
            reason_code="corrupt",
            message="处理失败：无法读取或解码该文件，可能已损坏、不完整或不是音视频。",
            url=original_url,
            out_dir=out_dir,
            inbox=inbox,
        )
        _emit(status, out_dir, human=proto.format_human(status), code=1)

    is_local = bool(
        args.mode == "file"
        or getattr(args, "as_file", False)
        or getattr(args, "_used_inbox_fallback", False)
        or getattr(args, "tier_hint", 1) == 2
    )
    if not is_local and args.input:
        candidate = Path(args.input).expanduser()
        if candidate.is_file() and not proto.looks_like_url(args.input):
            is_local = True
    tier = 2 if is_local else 1
    how = "使用了你提供的本地/inbox 文件" if is_local else "全自动下载"
    human = (
        f"完成：{out}\n"
        f"  档次：档 {tier}（{how}）\n"
        f"  联系图：{out / 'contact_sheet.png'}\n"
        f"  时间轴：{out / 'timeline.png'}\n"
        f"  报告：{out / 'report.md'}  {out / 'report.html'}  {out / 'report_page.png'}\n"
        f"  状态：{out / 'status.json'}"
    )
    status = proto.build_status(
        status="ok",
        tier=tier,
        reason_code="ok",
        message=("已完成分镜报告（档 2）。已使用你提供的本地或 inbox 文件。" if is_local else "已完成分镜报告（档 1）。全自动下载成功。"),
        platform=guess_platform(original_url or args.source_url or None) or ("local" if is_local else None),
        url=original_url or args.source_url or None,
        out_dir=out,
        inbox=inbox,
        extras={"contact_sheet": str(out / "contact_sheet.png"), "report": str(out / "report.html")},
    )
    _emit(status, out, human=human, code=None)


if __name__ == "__main__":
    main()

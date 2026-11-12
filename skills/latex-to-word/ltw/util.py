# -*- coding: utf-8 -*-
"""通用小函数：路径、注释剥离、花括号解析、罗马数字。"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional


def which(name: str) -> Optional[str]:
    return shutil.which(name)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def strip_tex_comments(text: str) -> str:
    """去掉未转义的 % 注释，保留换行。"""
    out = []
    for line in text.splitlines(keepends=True):
        i = 0
        buf = []
        while i < len(line):
            ch = line[i]
            if ch == "%" and (i == 0 or line[i - 1] != "\\"):
                if line.endswith("\n"):
                    buf.append("\n")
                break
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return "".join(out)


def skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i] in " \t\r\n":
        i += 1
    return i


def parse_braced(s: str, i: int):
    """从 s[i] 起解析 { ... }，返回 (内容, 结束位置)。无则 (None, i)。"""
    i0 = skip_ws(s, i)
    if i0 >= len(s) or s[i0] != "{":
        return None, i
    depth = 0
    j = i0
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n:
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i0 + 1:j], j + 1
        j += 1
    return s[i0 + 1:], n


def parse_bracketed(s: str, i: int):
    """可选参数 [ ... ]。没有 [ 则 (None, i)。"""
    i0 = skip_ws(s, i)
    if i0 >= len(s) or s[i0] != "[":
        return None, i
    depth = 0
    j = i0
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n:
            j += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return s[i0 + 1:j], j + 1
        j += 1
    return s[i0 + 1:], n


def parse_command_name(s: str, i: int):
    """s[i] 应为反斜杠。返回 (命令名不含斜杠, 结束位置)。"""
    if i >= len(s) or s[i] != "\\":
        return None, i
    j = i + 1
    if j >= len(s):
        return "\\", j
    if s[j].isalpha():
        while j < len(s) and s[j].isalpha():
            j += 1
        return s[i + 1:j], j
    return s[j], j + 1


def find_env_end(s: str, begin_pos: int, env: str) -> int:
    """begin_pos 指向 \\begin{env} 之后。返回 \\end{env} 之后的位置。"""
    pat_b = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
    pat_e = re.compile(r"\\end\{" + re.escape(env) + r"\}")
    depth = 1
    i = begin_pos
    while i < len(s) and depth:
        mb = pat_b.search(s, i)
        me = pat_e.search(s, i)
        if me is None:
            return len(s)
        if mb and mb.start() < me.start():
            depth += 1
            i = mb.end()
        else:
            depth -= 1
            i = me.end()
    return i


def split_top_level(s: str, sep: str):
    """按顶层 sep 切开（sep 通常是 r'\\\\'），忽略花括号和 begin/end 内部。"""
    parts = []
    buf = []
    i = 0
    n = len(s)
    depth = 0
    env_depth = 0
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            name, j = parse_command_name(s, i)
            if name == "begin":
                _, j2 = parse_braced(s, j)
                env_depth += 1
                buf.append(s[i:j2])
                i = j2
                continue
            if name == "end":
                _, j2 = parse_braced(s, j)
                env_depth = max(0, env_depth - 1)
                buf.append(s[i:j2])
                i = j2
                continue
        if env_depth == 0 and depth == 0 and s.startswith(sep, i):
            parts.append("".join(buf))
            buf = []
            i += len(sep)
            continue
        c = s[i]
        if c == "{" and (i == 0 or s[i - 1] != "\\"):
            depth += 1
        elif c == "}" and (i == 0 or s[i - 1] != "\\"):
            depth = max(0, depth - 1)
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def to_roman(n: int) -> str:
    if n <= 0:
        return str(n)
    vals = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out = []
    rest = n
    for v, s in vals:
        while rest >= v:
            out.append(s)
            rest -= v
    return "".join(out)


def labels_in(text: str):
    return re.findall(r"\\label\s*\{([^{}]+)\}", text)

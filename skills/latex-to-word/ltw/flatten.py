# -*- coding: utf-8 -*-
"""定位主 tex、递归展开 \\input / \\include。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .util import log, strip_tex_comments

MAIN_CANDIDATES = (
    "main.tex", "root.tex", "00-main.tex", "paper.tex", "ms.tex",
    "article.tex", "manuscript.tex", "sn-article.tex",
)

SKIP_INPUT = {
    "graphicx", "amsmath", "amssymb", "hyperref", "cleveref",
    "booktabs", "xcolor", "caption", "subcaption", "cite",
    "natbib", "inputenc", "fontenc", "babel",
}


def find_main_tex(path: Path) -> Path:
    if path.is_file():
        return path
    for name in MAIN_CANDIDATES:
        p = path / name
        if p.exists():
            return p
    found = []
    for p in path.rglob("*.tex"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\\documentclass\b", strip_tex_comments(t)):
            found.append(p)
    if not found:
        raise FileNotFoundError("失败：在 %s 找不到含 \\documentclass 的 tex 文件" % path)

    def rank(p: Path):
        n = p.name.lower()
        return (
            0 if n in MAIN_CANDIDATES else 1,
            len(p.relative_to(path).parts),
            len(n),
        )

    found.sort(key=rank)
    return found[0]


def resolve_tex_file(name: str, search_dirs) -> Optional[Path]:
    raw = name.strip().strip("{}")
    raw = raw.replace("/", os.sep)
    candidates = [raw]
    if not Path(raw).suffix:
        candidates += [raw + ".tex", raw + ".ltx", raw + ".sty"]
    for d in search_dirs:
        for c in candidates:
            p = d / c
            try:
                p = p.resolve()
            except OSError:
                continue
            if p.exists() and p.is_file():
                return p
    return None


def flatten_inputs(tex: str, main_file: Path, seen=None, project_root=None) -> str:
    if seen is None:
        seen = set()
    if project_root is None:
        project_root = main_file.parent
    root = main_file.parent
    search = [project_root, root]
    for sub in ("sections", "tables", "content", "tex", "src", "chapters", "body"):
        d = root / sub
        if d.is_dir():
            search.append(d)
    try:
        search.extend(x for x in root.iterdir() if x.is_dir())
    except OSError:
        pass

    def repl(m):
        cmd = m.group(1)
        fname = m.group(2).strip()
        if fname in SKIP_INPUT:
            return m.group(0)
        p = resolve_tex_file(fname, search)
        if p is None:
            log("[flatten] 找不到 \\%s{%s}，原样保留" % (cmd, fname))
            return m.group(0)
        key = str(p.resolve())
        if key in seen:
            log("[flatten] 跳过循环引用 %s" % p)
            return ""
        if p.suffix.lower() in {".sty", ".cls", ".bst"}:
            return m.group(0)
        seen.add(key)
        try:
            inner = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log("[flatten] 读 %s 失败：%s" % (p, e))
            return m.group(0)
        inner = strip_tex_comments(inner)
        inner = flatten_inputs(inner, p, seen, project_root=project_root)
        return "\n% ---- begin input " + p.name + " ----\n" + inner + "\n% ---- end input " + p.name + " ----\n"

    tex = strip_tex_comments(tex)
    tex = re.sub(r"\\(input|include)\s*\{([^{}]+)\}", repl, tex)
    return tex

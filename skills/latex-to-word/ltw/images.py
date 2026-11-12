# -*- coding: utf-8 -*-
"""把 \\includegraphics 的 PDF/EPS 转成 PNG，便于嵌入 Word。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .util import log, parse_braced, parse_bracketed, which


def convert_images(tex: str, project_dir: Path, work: Path):
    """返回 (新 tex, 成功列表, 失败列表)。"""
    img_dir = work / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    graphicspath = [project_dir]
    gm = re.search(r"\\graphicspath\s*\{(.+?)\}(?:\s|$)", tex, re.S)
    if gm:
        for p in re.findall(r"\{([^{}]+)\}", gm.group(1)):
            graphicspath.append(project_dir / p.strip().strip("/"))
    for sub in ("figures", "Figures", "figure", "fig", "imgs", "images",
                "graphics", "figs", "flash_figs"):
        d = project_dir / sub
        if d.is_dir():
            graphicspath.append(d)
    # 子目录也搜一层
    extra = []
    for g in list(graphicspath):
        try:
            extra.extend(x for x in g.iterdir() if x.is_dir())
        except OSError:
            pass
    graphicspath.extend(extra)

    pdftocairo = which("pdftocairo")
    successes, fails = [], []

    def find_image(name: str) -> Optional[Path]:
        name = name.strip().replace("\\", os.sep)
        exts = ["", ".png", ".jpg", ".jpeg", ".pdf", ".eps",
                ".PNG", ".JPG", ".JPEG", ".PDF", ".EPS"]
        for g in graphicspath:
            for e in exts:
                cand = g / (name + e if e and not name.lower().endswith(e.lower()) else name)
                if cand.exists():
                    return cand
        # 全局按文件名搜
        base = Path(name).name
        stem = Path(base).stem
        for p in project_dir.rglob("*"):
            if p.is_file() and (p.name == base or p.stem == stem or p.stem == Path(name).stem):
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".gif"}:
                    return p
        return None

    def convert_one(src: Path) -> Optional[Path]:
        suf = src.suffix.lower()
        if suf in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
            dest = img_dir / src.name
            if not dest.exists():
                try:
                    shutil.copy2(src, dest)
                except OSError as e:
                    fails.append("%s 复制失败：%s" % (src, e))
                    return None
            return dest
        if suf in {".pdf", ".eps"}:
            dest = img_dir / (src.stem + ".png")
            if dest.exists():
                return dest
            if not pdftocairo:
                fails.append("%s（无 pdftocairo，无法把 PDF 图转 PNG）" % src)
                return None
            cmd = [
                pdftocairo, "-png", "-singlefile", "-r", "150",
                str(src), str(dest.with_suffix("")),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=90)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                fails.append("%s 转 PNG 失败：%s" % (src, e))
                return None
            if dest.exists():
                successes.append("%s → %s" % (src.name, dest.name))
                return dest
            fails.append("%s 转 PNG 后文件不存在" % src)
            return None
        return src if src.exists() else None

    i = 0
    out = []
    n = len(tex)
    while i < n:
        if tex.startswith("\\includegraphics", i) and (i + 16 == n or not tex[i + 16].isalpha()):
            k = i + 16
            opt, k = parse_bracketed(tex, k)
            name, k2 = parse_braced(tex, k)
            if name is not None:
                # 去掉 \linewidth 等路径外的东西；取第一段
                name_clean = name.strip().split(",")[0].strip()
                src = find_image(name_clean)
                if src is None:
                    fails.append("找不到图片 %s" % name_clean)
                    out.append(tex[i:k2])
                    i = k2
                    continue
                dest = convert_one(src)
                if dest is None:
                    out.append(tex[i:k2])
                    i = k2
                    continue
                new_opt = "[%s]" % opt if opt is not None else ""
                out.append("\\includegraphics" + new_opt + "{" + str(dest) + "}")
                i = k2
                continue
        out.append(tex[i])
        i += 1
    return "".join(out), successes, fails

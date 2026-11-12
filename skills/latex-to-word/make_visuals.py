#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由脚本生成三栏前后对比 PNG：左=原 PDF，中=裸 pandoc，右=本 skill。

不得手工拼图。生成命令和 sha256 写入 visuals/MANIFEST.md。
依赖：LibreOffice（soffice）、pdftoppm、pdftotext、Python Pillow。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 16), b""):
            h.update(c)
    return h.hexdigest()


def which(n):
    return shutil.which(n)


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def soffice_to_pdf(docx: Path, outdir: Path, profile: Path) -> Path:
    soffice = which("soffice") or which("libreoffice")
    if not soffice:
        raise RuntimeError("找不到 LibreOffice（soffice）")
    profile.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # 独立用户配置，避免锁文件
    uri = "file://%s" % profile.resolve()
    cmd = [
        soffice, "--headless", "--norestore", "--nolockcheck",
        "-env:UserInstallation=%s" % uri,
        "--convert-to", "pdf",
        "--outdir", str(outdir),
        str(docx),
    ]
    run(cmd, timeout=180)
    pdf = outdir / (docx.stem + ".pdf")
    if not pdf.exists():
        # 有时名字被改
        pdfs = list(outdir.glob("*.pdf"))
        if not pdfs:
            raise RuntimeError("LibreOffice 未生成 PDF")
        pdf = pdfs[0]
    return pdf


def pdftoppm_page(pdf: Path, page: int, dest_png: Path, dpi: int = 150) -> Path:
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    prefix = dest_png.with_suffix("")
    cmd = [
        "pdftoppm", "-png", "-r", str(dpi),
        "-f", str(page), "-l", str(page),
        str(pdf), str(prefix),
    ]
    run(cmd, timeout=60)
    # pdftoppm writes prefix-N.png (N zero-padded)
    cands = sorted(prefix.parent.glob(prefix.name + "*.png"))
    if not cands:
        raise RuntimeError("pdftoppm 未生成 %s" % dest_png)
    # move/rename to dest
    if cands[0] != dest_png:
        shutil.copy2(cands[0], dest_png)
    return dest_png


def pdf_n_pages(pdf: Path) -> int:
    r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
    m = re.search(r"Pages:\s+(\d+)", r.stdout)
    return int(m.group(1)) if m else 0


def page_text(pdf: Path, page: int) -> str:
    r = subprocess.run(
        ["pdftotext", "-raw", "-f", str(page), "-l", str(page), str(pdf), "-"],
        capture_output=True,
    )
    return r.stdout.decode("utf-8", "replace")


def find_page(pdf: Path, needles) -> int:
    """返回第一个同时或分别命中 needles 的 1-based 页码。"""
    n = pdf_n_pages(pdf)
    if isinstance(needles, str):
        needles = [needles]
    # 优先：一页内出现任意 needle
    hits = []
    for i in range(1, n + 1):
        t = page_text(pdf, i)
        for nd in needles:
            if nd and nd in t:
                hits.append((i, nd))
                break
    if hits:
        return hits[0][0]
    return 1


def cjk_font(size: int):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf",
    ]
    # fc-list file
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size=size, index=0)
            except OSError:
                pass
    # search
    for root in (Path("/usr/share/fonts"),):
        for p in root.rglob("NotoSansCJK*.ttc"):
            try:
                return ImageFont.truetype(str(p), size=size, index=5)  # SC often index 5? try 0
            except OSError:
                try:
                    return ImageFont.truetype(str(p), size=size)
                except OSError:
                    continue
    return ImageFont.load_default()


def compose_three(left: Path, mid: Path, right: Path, titles, out: Path, header: str):
    imgs = [Image.open(p).convert("RGB") for p in (left, mid, right)]
    # 统一高度
    target_h = 1400
    scaled = []
    for im in imgs:
        w, h = im.size
        nw = int(w * target_h / h)
        scaled.append(im.resize((nw, target_h), Image.Resampling.LANCZOS))
    gap = 16
    title_h = 64
    header_h = 72
    footer_h = 48
    total_w = sum(im.size[0] for im in scaled) + gap * 4
    total_h = header_h + title_h + target_h + footer_h
    canvas = Image.new("RGB", (total_w, total_h), (248, 248, 246))
    draw = ImageDraw.Draw(canvas)
    font_h = cjk_font(28)
    font_t = cjk_font(22)
    font_f = cjk_font(16)
    # header
    draw.rectangle([0, 0, total_w, header_h], fill=(32, 56, 88))
    # center header text
    try:
        bbox = draw.textbbox((0, 0), header, font=font_h)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(header) * 16
    draw.text(((total_w - tw) // 2, 18), header, font=font_h, fill=(255, 255, 255))
    colors = [(36, 110, 80), (150, 70, 40), (30, 80, 140)]
    x = gap
    y = header_h
    for im, title, col in zip(scaled, titles, colors):
        draw.rectangle([x, y, x + im.size[0], y + title_h], fill=col)
        try:
            bbox = draw.textbbox((0, 0), title, font=font_t)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(title) * 12
        draw.text((x + (im.size[0] - tw) // 2, y + 16), title, font=font_t, fill=(255, 255, 255))
        canvas.paste(im, (x, y + title_h))
        # 边框
        draw.rectangle([x, y, x + im.size[0] - 1, y + title_h + im.size[1] - 1], outline=(60, 60, 60), width=2)
        x += im.size[0] + gap
    # footer
    foot = "由 make_visuals.py 自动生成，非手工拼图。页码由脚本按关键词定位。"
    draw.text((gap, header_h + title_h + target_h + 12), foot, font=font_f, fill=(80, 80, 80))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)
    for im in imgs + scaled:
        im.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--official-pdf", required=True)
    ap.add_argument("--bare-docx", required=True)
    ap.add_argument("--ours-docx", required=True)
    ap.add_argument("-o", "--output", required=True, help="输出 PNG")
    ap.add_argument("--official-needle", default="", help="定位原 PDF 页的关键词")
    ap.add_argument("--bare-needle", default="", help="定位裸 pandoc 页的关键词（如 [eq:ppd]）")
    ap.add_argument("--ours-needle", default="", help="定位本 skill 页的关键词（如 Equation 3）")
    ap.add_argument("--official-page", type=int, default=0)
    ap.add_argument("--bare-page", type=int, default=0)
    ap.add_argument("--ours-page", type=int, default=0)
    ap.add_argument("--header", default="LaTeX 论文转 Word：前后对比")
    ap.add_argument("--titles", default="原 PDF,裸 pandoc,本 skill")
    ap.add_argument("--workdir", default="")
    ap.add_argument("--manifest", default="")
    args = ap.parse_args()

    work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="ltw-vis-"))
    work.mkdir(parents=True, exist_ok=True)
    official = Path(args.official_pdf)
    bare_docx = Path(args.bare_docx)
    ours_docx = Path(args.ours_docx)
    out = Path(args.output)

    profile = work / "lo-profile"
    bare_pdf = soffice_to_pdf(bare_docx, work / "bare", profile / "bare")
    ours_pdf = soffice_to_pdf(ours_docx, work / "ours", profile / "ours")

    op = args.official_page or find_page(official, [x for x in args.official_needle.split("|") if x] or [""])
    bp = args.bare_page or find_page(bare_pdf, [x for x in args.bare_needle.split("|") if x] or [""])
    up = args.ours_page or find_page(ours_pdf, [x for x in args.ours_needle.split("|") if x] or [""])
    print("pages official=%d bare=%d ours=%d" % (op, bp, up))

    left = work / "left.png"
    mid = work / "mid.png"
    right = work / "right.png"
    pdftoppm_page(official, op, left)
    pdftoppm_page(bare_pdf, bp, mid)
    pdftoppm_page(ours_pdf, up, right)

    titles = [s.strip() for s in args.titles.split(",")]
    if len(titles) != 3:
        titles = ["原 PDF", "裸 pandoc", "本 skill"]
    titles = [
        "%s（p.%d）" % (titles[0], op),
        "%s（p.%d）" % (titles[1], bp),
        "%s（p.%d）" % (titles[2], up),
    ]
    compose_three(left, mid, right, titles, out, args.header)
    digest = sha256_file(out)
    print("WROTE", out, "sha256", digest)
    man = Path(args.manifest) if args.manifest else out.parent / "MANIFEST.md"
    cmd_line = "python3 make_visuals.py --official-pdf %s --bare-docx %s --ours-docx %s -o %s --official-needle %r --bare-needle %r --ours-needle %r --official-page %d --bare-page %d --ours-page %d" % (
        official, bare_docx, ours_docx, out,
        args.official_needle, args.bare_needle, args.ours_needle,
        op, bp, up,
    )
    prev = man.read_text(encoding="utf-8") if man.exists() else "# visuals 生成清单\n\n由 make_visuals.py 脚本出图，非手工拼图。\n\n"
    block = "\n## %s\n\n- 生成命令：`%s`\n- sha256：`%s`\n- 页码：原 PDF p.%d，裸 pandoc p.%d，本 skill p.%d\n- 关键词：official=%r bare=%r ours=%r\n" % (
        out.name, cmd_line, digest, op, bp, up,
        args.official_needle, args.bare_needle, args.ours_needle,
    )
    if out.name not in prev:
        man.write_text(prev + block, encoding="utf-8")
    else:
        # replace section
        man.write_text(prev, encoding="utf-8")
        # still append if not exact
        if digest not in prev:
            man.write_text(prev + block, encoding="utf-8")
    print("MANIFEST", man)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由脚本生成前后对比 PNG：左栏埋错页渲染，右栏同页加红色批注气泡，底部汇总表。

LibreOffice 把 docx 转成 PDF 时不会画出 Word 批注气泡，因此右栏在同一次
LibreOffice 渲染之上，按批注锚点由本脚本补画红色编号框和右侧气泡。
交给用户的输出文件里仍是真正的 Word 批注。不得手工拼图。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

DPI = 150
SIDEBAR_W = 420
MARGIN = 24
TITLE_H = 56
FOOTER_NOTE_H = 48
RED = (200, 32, 32)
RED_LIGHT = (255, 236, 236)
DARK = (30, 30, 30)
GRAY = (90, 90, 90)
GREEN = (20, 120, 60)
ORANGE = (180, 90, 10)
HEADER_BG = (245, 245, 247)
LINE = (210, 210, 214)

FONT_TTC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_TTC_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SC_INDEX = 2


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_TTC_BOLD if bold else FONT_TTC
    return ImageFont.truetype(path, size, index=SC_INDEX)


def soffice_to_pdf(docx: Path, out_dir: Path, profile: Path, fonts_conf: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["FONTCONFIG_FILE"] = str(fonts_conf)
    env["SAL_DISABLE_OPENCL"] = "1"
    cmd = [
        "soffice",
        "--headless",
        "--norestore",
        "--nologo",
        "--nolockcheck",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(docx),
    ]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    pdf = out_dir / (docx.stem + ".pdf")
    if r.returncode != 0 or not pdf.is_file():
        raise RuntimeError(
            f"LibreOffice 转 PDF 失败（{docx}）:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
    return pdf, cmd, r.stdout + r.stderr


def pdf_to_pngs(pdf: Path, out_prefix: Path, dpi: int) -> list[Path]:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(out_prefix)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdftoppm 失败: {r.stderr}")
    pages = sorted(out_prefix.parent.glob(out_prefix.name + "-*.png"))
    if not pages:
        raise RuntimeError(f"pdftoppm 没有产出页面：{out_prefix}")
    return pages


def pdf_bbox(pdf: Path, xml_path: Path) -> list[dict]:
    cmd = ["pdftotext", "-bbox", str(pdf), str(xml_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdftotext -bbox 失败: {r.stderr}")
    root = etree.parse(str(xml_path)).getroot()
    pages = []
    for i, page in enumerate(root.xpath("//*[local-name()='page']"), start=1):
        words = []
        for w in page.xpath(".//*[local-name()='word']"):
            words.append({
                "text": w.text or "",
                "xMin": float(w.get("xMin")),
                "yMin": float(w.get("yMin")),
                "xMax": float(w.get("xMax")),
                "yMax": float(w.get("yMax")),
            })
        pages.append({
            "number": i,
            "width": float(page.get("width")),
            "height": float(page.get("height")),
            "words": words,
            "joined": "".join(w["text"] for w in words),
        })
    return pages, cmd


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").replace("　", "").replace("\n", "")


def _is_toc_like(s: str) -> bool:
    t = s or ""
    if "..." in t or "…" in t or "···" in t or "．．．．" in t:
        return True
    if t.count(".") >= 6:
        return True
    return False


def locate_anchor(pages: list[dict], needle: str) -> list[dict]:
    """在各页 bbox 中找完整 needle。跳过紧挨点线的手工目录行，取最短完整窗口。"""
    raw = (needle or "").strip()
    if not raw:
        return []
    cand_n = _norm(raw)
    if len(cand_n) < 2:
        return []
    # 过长针只取前 20 个规范字符，足够定位且避免跨段
    if len(cand_n) > 20:
        cand_n = cand_n[:20]
    hits = []
    seen = set()
    for page in pages:
        words = page["words"]
        n = len(words)
        for i in range(n):
            acc = ""
            xMin = yMin = 1e9
            xMax = yMax = 0.0
            last_j = i
            near_toc = False
            if _is_toc_like(words[i]["text"]):
                continue
            for j in range(i, min(n, i + 10)):
                if _is_toc_like(words[j]["text"]):
                    near_toc = True
                    break
                if words[j]["yMin"] - (yMin if yMin < 1e8 else words[j]["yMin"]) > 16:
                    break
                acc += words[j]["text"]
                xMin = min(xMin, words[j]["xMin"])
                yMin = min(yMin, words[j]["yMin"])
                xMax = max(xMax, words[j]["xMax"])
                yMax = max(yMax, words[j]["yMax"])
                last_j = j
                acc_n = _norm(acc)
                if cand_n in acc_n:
                    # 邻域若是点线，视为目录条目，丢掉
                    for k in range(max(0, i - 1), min(n, j + 3)):
                        if _is_toc_like(words[k]["text"]):
                            near_toc = True
                            break
                    if near_toc:
                        break
                    key = (page["number"], round(xMin, 1), round(yMin, 1))
                    if key not in seen:
                        seen.add(key)
                        hits.append({
                            "page": page["number"],
                            "xMin": xMin, "yMin": yMin,
                            "xMax": xMax, "yMax": yMax,
                            "matched": acc,
                            "tight": len(acc_n),
                            "near_toc": False,
                        })
                    break
    # 完整匹配里取窗口最短的，同分则取页码较大的（正文通常在目录之后）
    hits.sort(key=lambda h: (h.get("tight", 999), -h["page"]))
    return hits


def assign_findings_to_pages(findings: list[dict], pages: list[dict]) -> dict[int, list]:
    by_page: dict[int, list] = {p["number"]: [] for p in pages}
    unplaced = []
    for f in findings:
        needles = []
        pt = (f.get("paragraph_text") or "").strip()
        if pt:
            needles.append(pt[:24])
            # 优先用【Exx】标记
            import re
            m = re.search(r"【E\d+】", pt)
            if m:
                needles.insert(0, m.group(0))
        if f.get("anchor"):
            needles.append(str(f["anchor"]))
        hits = []
        for n in needles:
            hits = locate_anchor(pages, n)
            if hits:
                break
        if not hits:
            unplaced.append(f)
            # 节级问题：放到该节第一页的估计——用 message 再试
            hits = locate_anchor(pages, (f.get("message") or "")[:8])
        if hits:
            # 取第一处
            h = hits[0]
            f = dict(f)
            f["_box"] = h
            by_page[h["page"]].append(f)
        else:
            unplaced.append(f)
    # 未定位的放到第 1 页侧栏，不画框
    for f in unplaced:
        f = dict(f)
        f["_box"] = None
        by_page[1].append(f)
    return by_page


def wrap_cn(text: str, max_chars: int) -> list[str]:
    lines = []
    text = text or ""
    for para in text.split("\n"):
        s = para
        while len(s) > max_chars:
            lines.append(s[:max_chars])
            s = s[max_chars:]
        lines.append(s)
    return lines or [""]


def draw_page_with_bubbles(page_img: Image.Image, items: list[dict], page_w_pt: float, dpi: int) -> Image.Image:
    """在页面右侧加侧栏，页内锚点画红框和编号。"""
    scale = dpi / 72.0
    w, h = page_img.size
    canvas = Image.new("RGB", (w + SIDEBAR_W, h), (255, 255, 255))
    canvas.paste(page_img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    # 分界线
    draw.line([(w + 2, 0), (w + 2, h)], fill=RED, width=3)

    # 侧栏标题
    f_title = font(15, bold=True)
    f_body = font(13, bold=False)
    f_num = font(13, bold=True)
    draw.rectangle([w + 3, 0, w + SIDEBAR_W, 36], fill=RED)
    draw.text((w + 14, 8), "本页批注（脚本按锚点补画）", font=f_title, fill=(255, 255, 255))

    # 编号并画框
    y_cursor = 48
    card_w = SIDEBAR_W - 20
    for idx, item in enumerate(items, start=1):
        box = item.get("_box")
        if box:
            x0 = int(box["xMin"] * scale) - 3
            y0 = int(box["yMin"] * scale) - 3
            x1 = int(box["xMax"] * scale) + 3
            y1 = int(box["yMax"] * scale) + 3
            x0 = max(0, min(x0, w - 2))
            x1 = max(x0 + 8, min(x1, w - 1))
            y0 = max(0, min(y0, h - 2))
            y1 = max(y0 + 8, min(y1, h - 1))
            draw.rectangle([x0, y0, x1, y1], outline=RED, width=3)
            # 编号圆
            cx, cy = x0 - 2, y0 - 2
            if cx < 16:
                cx = x1 + 2
            r = 11
            draw.ellipse([cx, cy, cx + 2 * r, cy + 2 * r], fill=RED, outline=RED)
            num = str(idx)
            tw = draw.textlength(num, font=f_num)
            draw.text((cx + r - tw / 2, cy + 2), num, font=f_num, fill=(255, 255, 255))

        msg = item.get("message") or ""
        lines = wrap_cn(msg, 16)
        card_h = 10 + 18 * (len(lines) + 1)
        if y_cursor + card_h > h - 8:
            # 放不下就压缩字数
            lines = lines[:4] + (["……"] if len(lines) > 4 else [])
            card_h = 10 + 18 * (len(lines) + 1)
        draw.rounded_rectangle(
            [w + 10, y_cursor, w + 10 + card_w, y_cursor + card_h],
            radius=6, fill=RED_LIGHT, outline=RED, width=2,
        )
        draw.ellipse([w + 16, y_cursor + 6, w + 38, y_cursor + 28], fill=RED)
        tw = draw.textlength(str(idx), font=f_num)
        draw.text((w + 27 - tw / 2, y_cursor + 8), str(idx), font=f_num, fill=(255, 255, 255))
        draw.text((w + 44, y_cursor + 8), (item.get("category") or ""), font=f_title, fill=RED)
        ty = y_cursor + 28
        for ln in lines:
            draw.text((w + 16, ty), ln, font=f_body, fill=DARK)
            ty += 18
        y_cursor += card_h + 8
        if y_cursor > h - 40:
            leftover = len(items) - idx
            if leftover > 0:
                draw.text((w + 16, y_cursor), f"另有 {leftover} 条见底部汇总表", font=f_body, fill=GRAY)
            break
    return canvas


def draw_summary(compare: dict, gold: dict, width: int) -> Image.Image:
    f_h = font(20, bold=True)
    f_sub = font(15, bold=False)
    f_th = font(14, bold=True)
    f_td = font(13, bold=False)
    n_gold = compare["n_gold"]
    n_hit = compare["n_hit"]
    n_miss = compare["n_miss"]
    n_fp = compare["n_false_positive"]
    rows = []
    hit_ids = {h["id"] for h in compare.get("hits") or []}
    for e in gold.get("errors") or []:
        status = "查出" if e["id"] in hit_ids else "漏检"
        rows.append((e["id"], e["category"], e["description"], status))
    for fp in compare.get("false_positives") or []:
        rows.append(("—", fp.get("category") or "", "误报：" + (fp.get("message") or ""), "误报"))

    row_h = 32
    header_block = 110
    height = header_block + 36 + row_h * (len(rows) + 1) + 20
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, header_block], fill=HEADER_BG)
    title = f"汇总：在预先公开的 {n_gold} 处埋错上，查出 {n_hit} 处，漏检 {n_miss} 处，误报 {n_fp} 处"
    draw.text((MARGIN, 16), title, font=f_h, fill=DARK)
    note = (
        "以上数字只说明「在这份虚构样例、这一次跑次上的结果」，不是准确率，也不能写成零差错，不能外推到任意学校规范。"
        "同一批不重跑凑数。漏检和误报都记入对照结果（compare.json）。"
    )
    # wrap note
    y = 50
    for ln in wrap_cn(note, 72):
        draw.text((MARGIN, y), ln, font=f_sub, fill=GRAY)
        y += 22

    cols = [70, 200, width - 280, 90]  # widths
    headers = ["编号", "类别", "说明", "结果"]
    x0, y0 = MARGIN, header_block + 10
    table_w = width - 2 * MARGIN
    # column x positions
    cw = [70, 210, table_w - 70 - 210 - 80, 80]
    xs = [x0]
    for w_ in cw[:-1]:
        xs.append(xs[-1] + w_)

    def row_color(status):
        if status == "查出":
            return (230, 245, 234)
        if status == "漏检":
            return (255, 230, 230)
        if status == "误报":
            return (255, 242, 220)
        return (255, 255, 255)

    # header row
    draw.rectangle([x0, y0, x0 + table_w, y0 + row_h], fill=(50, 50, 55))
    for x, head in zip(xs, headers):
        draw.text((x + 8, y0 + 7), head, font=f_th, fill=(255, 255, 255))
    y = y0 + row_h
    for rid, cat, desc, status in rows:
        bg = row_color(status)
        draw.rectangle([x0, y, x0 + table_w, y + row_h], fill=bg, outline=LINE)
        vals = [rid, cat, desc, status]
        # truncate desc
        desc_max = 42
        if len(vals[2]) > desc_max:
            vals[2] = vals[2][:desc_max] + "…"
        fills = [DARK, DARK, DARK, GREEN if status == "查出" else (RED if status == "漏检" else ORANGE)]
        for x, val, fl, ft in zip(xs, vals, fills, [f_td, f_td, f_td, f_th]):
            draw.text((x + 8, y + 7), val, font=ft, fill=fl)
        y += row_h
    return img


def compose(before_pages: list[Path], after_drawn: dict[int, Image.Image],
            chosen: list[int], compare: dict, gold: dict, note: str) -> Image.Image:
    f_title = font(22, bold=True)
    f_note = font(14, bold=False)
    # Measure
    samples = []
    for n in chosen:
        left = Image.open(before_pages[n - 1]).convert("RGB")
        right = after_drawn[n]
        samples.append((n, left, right))
    # scale left to same height as original (right is wider)
    pair_h = samples[0][1].height
    # Make left canvas same width as right for alignment? No - left is page only, right is page+sidebar.
    # Total width = margin + left_w + gap + right_w + margin
    left_w = samples[0][1].width
    right_w = samples[0][2].width
    gap = 18
    width = MARGIN + left_w + gap + right_w + MARGIN
    # header + pairs + footer note + summary
    note_lines = wrap_cn(note, 78)
    note_h = 16 + 22 * len(note_lines)
    summary = draw_summary(compare, gold, width)
    height = TITLE_H + note_h + (TITLE_H + pair_h) * len(samples) + 24 + summary.height + MARGIN
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # top banner
    draw.rectangle([0, 0, width, TITLE_H], fill=(40, 40, 48))
    draw.text(
        (MARGIN, 14),
        "毕业论文格式自查 · 前后对比（脚本生成，非手工拼图）",
        font=f_title,
        fill=(255, 255, 255),
    )
    y = TITLE_H + 8
    for n, left, right in samples:
        draw.text((MARGIN, y), f"左：埋错样例第 {n} 页（检查前）", font=font(16, True), fill=DARK)
        draw.text((MARGIN + left_w + gap, y), f"右：同页，按 Word 批注锚点补画红色气泡", font=font(16, True), fill=RED)
        y += 32
        img.paste(left, (MARGIN, y))
        img.paste(right, (MARGIN + left_w + gap, y))
        y += pair_h + 16
    for i, ln in enumerate(note_lines):
        draw.text((MARGIN, y + i * 22), ln, font=f_note, fill=GRAY)
    y += note_h
    img.paste(summary, (0, y))
    return img


def pick_pages(by_page: dict[int, list], n: int = 2) -> list[int]:
    ranked = sorted(by_page.items(), key=lambda kv: (-len([i for i in kv[1] if i.get("_box")]), kv[0]))
    chosen = [p for p, items in ranked if any(i.get("_box") for i in items)][:n]
    if not chosen:
        chosen = [1]
    return sorted(chosen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, help="埋错样例 docx")
    parser.add_argument("--after", required=True, help="带批注的 docx")
    parser.add_argument("--findings", required=True)
    parser.add_argument("--compare", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--out", required=True, help="输出 PNG")
    parser.add_argument("--meta", required=True, help="记录命令与 sha256 的 GENERATE.md")
    parser.add_argument("--fonts-conf", default=str(Path(__file__).resolve().parent / "fonts.conf"))
    parser.add_argument("--dpi", type=int, default=DPI)
    parser.add_argument("--workdir", default="")
    args = parser.parse_args()

    before = Path(args.before).resolve()
    after = Path(args.after).resolve()
    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    compare = json.loads(Path(args.compare).read_text(encoding="utf-8"))
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    out = Path(args.out).resolve()
    meta = Path(args.meta).resolve()
    fonts_conf = Path(args.fonts_conf).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="thesis-visual-"))
    work.mkdir(parents=True, exist_ok=True)
    profile = work / "lo_profile"
    profile.mkdir(exist_ok=True)
    pdf_dir = work / "pdf"
    png_dir = work / "png"
    png_dir.mkdir(exist_ok=True)

    cmds = []
    t0 = time.time()
    pdf_before, cmd1, log1 = soffice_to_pdf(before, pdf_dir, profile, fonts_conf)
    cmds.append(cmd1)
    pdf_after, cmd2, log2 = soffice_to_pdf(after, pdf_dir, profile, fonts_conf)
    cmds.append(cmd2)
    before_pngs = pdf_to_pngs(pdf_before, png_dir / "before", args.dpi)
    after_pngs = pdf_to_pngs(pdf_after, png_dir / "after", args.dpi)
    bbox_path = work / "bbox.xml"
    pages, cmd3 = pdf_bbox(pdf_before, bbox_path)
    cmds.append(cmd3)

    by_page = assign_findings_to_pages(findings.get("findings") or [], pages)
    chosen = pick_pages(by_page, 3)
    after_drawn = {}
    for n in chosen:
        img = Image.open(after_pngs[n - 1]).convert("RGB")
        after_drawn[n] = draw_page_with_bubbles(
            img, by_page.get(n) or [], pages[n - 1]["width"], args.dpi
        )

    note = (
        "出图说明：页面由 LibreOffice 25 headless 将 docx 转为 PDF，再用 pdftoppm 光栅化；"
        "LibreOffice 导出 PDF 时不渲染 Word 批注气泡，右栏红色编号框和侧栏气泡由本脚本按批注锚点与 pdftotext -bbox 位置补画。"
        "交给用户的输出 docx 里是真正的 Word 批注。本图由脚本一次生成，没有手工拼图。"
        f" 出图用字体映射见 visuals/fonts.conf（宋体→Noto Serif CJK SC，黑体/楷体→Noto Sans CJK SC），仅影响渲染，不影响检查。"
    )
    composed = compose(before_pngs, after_drawn, chosen, compare, gold, note)
    composed.save(str(out), "PNG")
    elapsed = time.time() - t0

    lo_ver = subprocess.run(["soffice", "--version"], capture_output=True, text=True).stdout.strip()
    lines = [
        "# 可视化生成记录",
        "",
        "本文件由 `visuals/generate_visual.py` 写出，记录命令、版本与 sha256，供复核。",
        "图是脚本生成的，不是手工拼图。",
        "",
        "## 命令",
        "",
        "```bash",
        f"python3 visuals/generate_visual.py \\",
        f"  --before {before} \\",
        f"  --after {after} \\",
        f"  --findings {args.findings} \\",
        f"  --compare {args.compare} \\",
        f"  --gold {args.gold} \\",
        f"  --out {out} \\",
        f"  --meta {meta} \\",
        f"  --fonts-conf {fonts_conf} \\",
        f"  --dpi {args.dpi}",
        "```",
        "",
        "内部调用：",
        "",
        "```",
    ]
    for c in cmds:
        lines.append(" ".join(str(x) for x in c))
    lines += [
        "```",
        "",
        "## 环境",
        "",
        f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')} Asia/Macau（UTC+8）",
        f"- 耗时：{elapsed:.1f} 秒",
        f"- LibreOffice：{lo_ver}",
        f"- pdftoppm / pdftotext：poppler，DPI={args.dpi}",
        f"- 选用页：{chosen}",
        "",
        "## 说明",
        "",
        "- LibreOffice 将 docx 转为 PDF 时不画出 Word 批注气泡，因此右栏在同页渲染之上，由脚本按批注锚点和 `pdftotext -bbox` 坐标补画红色编号框与侧栏气泡。",
        "- 交给用户的输出 docx 里是 python-docx 写入的真正 Word 批注。",
        "- `fonts.conf` 只用于出图时把「宋体 / 黑体 / 楷体」映射到本机 Noto CJK，让字体错误在图上能看出差别；检查脚本读的是 docx 里登记的字体名。",
        "",
        "## sha256",
        "",
        "下列哈希是各文件**全文**的 sha256。本记录本身不计算、不写入自哈希",
        "（避免「追加自哈希行之前的内容哈希」与整文件哈希对不上）。",
        "",
        "| 文件 | 含义 | sha256 |",
        "| --- | --- | --- |",
        f"| `{before}` | 埋错样例 | `{sha256_file(before)}` |",
        f"| `{after}` | 带批注文档 | `{sha256_file(after)}` |",
        f"| `{Path(args.findings).resolve()}` | 检查结果 findings.json | `{sha256_file(Path(args.findings))}` |",
        f"| `{Path(args.compare).resolve()}` | 对照结果 compare.json | `{sha256_file(Path(args.compare))}` |",
        f"| `{Path(args.gold).resolve()}` | 预先公开的错误清单 | `{sha256_file(Path(args.gold))}` |",
        f"| `{out}` | 本脚本生成的前后对比图 | `{sha256_file(out)}` |",
        "",
    ]
    meta.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes), sha256={sha256_file(out)}")
    print(f"wrote {meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

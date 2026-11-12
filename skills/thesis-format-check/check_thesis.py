#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按结构化规则检查毕业论文 docx，并把问题写成 Word 批注。

数据不出本机，不调用外部接口，不用 GPU。
规则文件须由用户（或 agent 根据用户提供的规范）写成结构化 JSON；
本仓库附带的 example_rules.json 是虚构示例，不冒充任何真实学校规范。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# 1 cm = 360000 EMU；1 pt = 12700 EMU；1 twip = 635 EMU
EMU_PER_CM = 360000.0
EMU_PER_PT = 12700.0
TWIPS_PER_PT = 20.0

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")

CHAPTER_RE = re.compile(r"^第([一二三四五六七八九十百零〇○0-9]+)章")
DOTTED_RE = re.compile(r"^(\d+(?:\.\d+)+)\s")
FIG_CAPTION_RE = re.compile(r"^图\s*([0-9]+|[一二三四五六七八九十百]+)\s*(.*)$")
TBL_CAPTION_RE = re.compile(r"^表\s*([0-9]+|[一二三四五六七八九十百]+)\s*(.*)$")
REF_RE = re.compile(r"^\[(\d+)\]\s*(.*)$")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

CN_DIGITS = {
    "零": 0, "〇": 0, "○": 0,
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}


def cn_or_digit_to_int(s: str) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s == "百":
        return 100
    try:
        if len(s) == 1 and s in CN_DIGITS:
            return CN_DIGITS[s]
        if s.startswith("十") and len(s) == 2 and s[1] in CN_DIGITS:
            return 10 + CN_DIGITS[s[1]]
        if len(s) == 2 and s[1] == "十" and s[0] in CN_DIGITS:
            return CN_DIGITS[s[0]] * 10
        if len(s) == 3 and s[1] == "十" and s[0] in CN_DIGITS and s[2] in CN_DIGITS:
            return CN_DIGITS[s[0]] * 10 + CN_DIGITS[s[2]]
    except KeyError:
        return None
    return None


def is_arabic_number(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", (s or "").strip()))


@dataclass
class Finding:
    key: str
    category: str
    message: str
    paragraph_text: str = ""
    paragraph_index: Optional[int] = None
    section: Optional[int] = None  # 1-based
    side: Optional[str] = None
    anchor: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "category": self.category,
            "message": self.message,
            "paragraph_text": self.paragraph_text[:200],
            "paragraph_index": self.paragraph_index,
            "section": self.section,
            "side": self.side,
            "anchor": self.anchor,
        }


def load_rules(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("规则文件必须是 JSON 对象")
    return data


def elm(tag: str):
    return qn(f"w:{tag}")


def style_name(p: Paragraph) -> str:
    try:
        st = p.style
        return st.name if st is not None else ""
    except Exception:
        return ""


def looks_like_toc_entry(text: str) -> bool:
    """手工目录行：一串前导符后跟页码，不能当成真正的章标题。"""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"\.{3,}|…{2,}|·{3,}", t):
        return True
    if re.search(r"\s{2,}\d+\s*$", t) and len(t) > 8:
        return True
    return False


def heading_level(p: Paragraph) -> Optional[int]:
    text = (p.text or "").strip()
    # 手工目录行即使看起来像「第1章 … 1」，也不当作标题
    if looks_like_toc_entry(text):
        return None
    name = style_name(p)
    m = re.match(r"^(?:Heading|标题)\s*(\d+)$", name, re.I)
    if m:
        return int(m.group(1))
    pPr = p._p.pPr
    if pPr is not None:
        el = pPr.find(elm("outlineLvl"))
        if el is not None:
            val = el.get(elm("val"))
            if val is not None:
                try:
                    return int(val) + 1
                except ValueError:
                    pass
    # 「参考文献」等即使写成 Heading 1，也不当章标题（样式名仍可能是 Heading 1，
    # 上面已经返回了）。这里只处理纯文本、无标题样式的情形。
    for s in ("参考文献", "致谢", "附录", "摘要", "目录", "Abstract", "ABSTRACT"):
        if text == s or text.startswith(s + " ") or text.startswith(s + "　"):
            return None
    if CHAPTER_RE.match(text) and len(text) < 80:
        return 1
    if re.match(r"^\d+\.\d+\.\d+\s+\S", text) and len(text) < 80:
        return 3
    if re.match(r"^\d+\.\d+\s+\S", text) and len(text) < 80:
        return 2
    return None


def iter_style_chain(paragraph: Paragraph) -> Iterable[Any]:
    try:
        style = paragraph.style
    except Exception:
        return
    seen = set()
    while style is not None:
        sid = getattr(style, "style_id", id(style))
        if sid in seen:
            break
        seen.add(sid)
        yield style
        try:
            style = style.base_style
        except Exception:
            break


def _rfonts_get(rFonts, key: str) -> Optional[str]:
    if rFonts is None:
        return None
    return rFonts.get(elm(key)) or rFonts.get(key)


def _sz_to_pt(sz_el) -> Optional[float]:
    if sz_el is None:
        return None
    val = sz_el.get(elm("val"))
    if val is None:
        return None
    try:
        return float(val) / 2.0
    except ValueError:
        return None


def _bold_from_rpr(rPr) -> Optional[bool]:
    if rPr is None:
        return None
    b = rPr.find(elm("b"))
    if b is None:
        return None
    val = b.get(elm("val"))
    if val is None:
        return True
    return val not in ("0", "false", "off", "False")


def _doc_defaults_rpr(doc: Document):
    styles = doc.styles.element
    dd = styles.find(elm("docDefaults"))
    if dd is None:
        return None
    rPrDefault = dd.find(elm("rPrDefault"))
    if rPrDefault is None:
        return None
    return rPrDefault.find(elm("rPr"))


def _style_rpr(style) -> Optional[Any]:
    try:
        el = style.element
    except Exception:
        return None
    return el.find(elm("rPr"))


def resolve_run_format(run, paragraph: Paragraph, doc: Document) -> dict:
    """沿 run → 段落样式链 → 文档默认 解析有效字体/字号/加粗。"""
    east_asia = None
    ascii_font = None
    size_pt = None
    bold = None

    def apply_rpr(rPr, overwrite_none_only=False):
        nonlocal east_asia, ascii_font, size_pt, bold
        if rPr is None:
            return
        rFonts = rPr.find(elm("rFonts"))
        ea = _rfonts_get(rFonts, "eastAsia")
        asc = _rfonts_get(rFonts, "ascii")
        han = _rfonts_get(rFonts, "hAnsi")
        sz = _sz_to_pt(rPr.find(elm("sz")))
        b = _bold_from_rpr(rPr)
        if overwrite_none_only:
            if east_asia is None and ea:
                east_asia = ea
            if ascii_font is None and (asc or han):
                ascii_font = asc or han
            if size_pt is None and sz is not None:
                size_pt = sz
            if bold is None and b is not None:
                bold = b
        else:
            if ea:
                east_asia = ea
            if asc or han:
                ascii_font = asc or han
            if sz is not None:
                size_pt = sz
            if b is not None:
                bold = b

    # 低优先级先填，高优先级覆盖：先 defaults 和样式，再 run 直接格式
    apply_rpr(_doc_defaults_rpr(doc), overwrite_none_only=True)
    # style chain: base first, then derived (iter is derived first, so apply reverse)
    chain = list(iter_style_chain(paragraph))
    for st in reversed(chain):
        apply_rpr(_style_rpr(st), overwrite_none_only=False)
    # paragraph-level rPr
    pPr = paragraph._p.pPr
    if pPr is not None:
        apply_rpr(pPr.find(elm("rPr")), overwrite_none_only=False)
    # run direct
    apply_rpr(run._element.find(elm("rPr")), overwrite_none_only=False)
    return {
        "eastAsia": east_asia,
        "ascii": ascii_font,
        "size_pt": size_pt,
        "bold": bold,
    }


def paragraph_line_spacing(paragraph: Paragraph, doc: Document) -> Optional[float]:
    """返回行距倍数（1.5 表示 1.5 倍）；固定值无法换算时返回 None。"""
    pf = paragraph.paragraph_format
    rule = pf.line_spacing_rule
    value = pf.line_spacing
    if value is not None:
        # 倍数（float）或 Length（固定行距）
        if isinstance(value, (int, float)) and not hasattr(value, "twips"):
            return float(value)
        # python-docx Length: 若 rule 是 EXACTLY / AT_LEAST，不换算成倍数
        try:
            from docx.enum.text import WD_LINE_SPACING
            if rule in (WD_LINE_SPACING.EXACTLY, WD_LINE_SPACING.AT_LEAST):
                return None
            if rule == WD_LINE_SPACING.SINGLE:
                return 1.0
            if rule == WD_LINE_SPACING.ONE_POINT_FIVE:
                return 1.5
            if rule == WD_LINE_SPACING.DOUBLE:
                return 2.0
            if rule == WD_LINE_SPACING.MULTIPLE:
                return float(value)
        except Exception:
            pass
        # lineRule=auto 时，line 的单位是 240 分之一行
        pPr = paragraph._p.pPr
        if pPr is not None:
            sp = pPr.find(elm("spacing"))
            if sp is not None:
                line = sp.get(elm("line"))
                line_rule = (sp.get(elm("lineRule")) or "auto")
                if line and line_rule in ("auto", None, ""):
                    try:
                        return float(line) / 240.0
                    except ValueError:
                        return None
        return None
    # 继承样式
    for st in iter_style_chain(paragraph):
        try:
            pf2 = st.paragraph_format
            if pf2.line_spacing is not None:
                if isinstance(pf2.line_spacing, (int, float)) and not hasattr(pf2.line_spacing, "twips"):
                    return float(pf2.line_spacing)
        except Exception:
            continue
        el = st.element.find(elm("pPr"))
        if el is not None:
            sp = el.find(elm("spacing"))
            if sp is not None:
                line = sp.get(elm("line"))
                line_rule = (sp.get(elm("lineRule")) or "auto")
                if line and line_rule in ("auto", None, ""):
                    try:
                        return float(line) / 240.0
                    except ValueError:
                        continue
    return None


def paragraph_first_indent_chars(paragraph: Paragraph, size_pt: Optional[float]) -> Optional[float]:
    """首行缩进（字符数）。读 firstLineChars，否则用绝对缩进 / 字号换算。"""
    pPr = paragraph._p.pPr
    ind = None
    if pPr is not None:
        ind = pPr.find(elm("ind"))
    if ind is not None:
        chars = ind.get(elm("firstLineChars"))
        if chars is not None:
            try:
                # 200 表示 2.00 字符
                return float(chars) / 100.0
            except ValueError:
                pass
        first = ind.get(elm("firstLine"))
        hanging = ind.get(elm("hanging"))
        if hanging is not None and (first is None or first == "0"):
            return 0.0
        if first is not None:
            try:
                twips = float(first)
                sz = size_pt or 12.0
                if sz <= 0:
                    return None
                return twips / (sz * TWIPS_PER_PT)
            except ValueError:
                pass
    # 样式链
    for st in iter_style_chain(paragraph):
        el = st.element.find(elm("pPr"))
        if el is None:
            continue
        ind = el.find(elm("ind"))
        if ind is None:
            continue
        chars = ind.get(elm("firstLineChars"))
        if chars is not None:
            try:
                return float(chars) / 100.0
            except ValueError:
                pass
        first = ind.get(elm("firstLine"))
        if first is not None:
            try:
                twips = float(first)
                sz = size_pt or 12.0
                return twips / (sz * TWIPS_PER_PT)
            except ValueError:
                pass
    pf = paragraph.paragraph_format
    if pf.first_line_indent is not None:
        try:
            twips = pf.first_line_indent.twips
            sz = size_pt or 12.0
            return twips / (sz * TWIPS_PER_PT)
        except Exception:
            pass
    return 0.0  # 未设置视为 0


def emu_to_cm(emu: int) -> float:
    return emu / EMU_PER_CM


def section_margins_cm(section) -> dict:
    return {
        "top": section.top_margin.cm if section.top_margin is not None else None,
        "bottom": section.bottom_margin.cm if section.bottom_margin is not None else None,
        "left": section.left_margin.cm if section.left_margin is not None else None,
        "right": section.right_margin.cm if section.right_margin is not None else None,
    }


def has_page_field(element) -> bool:
    if element is None:
        return False
    for instr in element.iter(elm("instrText")):
        text = "".join(instr.itertext()) if instr.text is None else (instr.text or "")
        # 也收集 tail / 子文本
        if instr.text:
            text = instr.text
        else:
            text = "".join(instr.itertext())
        up = text.upper()
        if re.search(r"\bPAGE\b", up) and "PAGEREF" not in up:
            return True
    for fld in element.iter(elm("fldSimple")):
        instr = fld.get(elm("instr")) or ""
        up = instr.upper()
        if re.search(r"\bPAGE\b", up) and "PAGEREF" not in up:
            return True
    return False


def header_footer_text(hf) -> str:
    parts = []
    try:
        for p in hf.paragraphs:
            parts.append(p.text or "")
        for table in hf.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text or "")
    except Exception:
        pass
    return "\n".join(parts)


def section_pg_num_type(section) -> dict:
    sectPr = section._sectPr
    el = sectPr.find(elm("pgNumType")) if sectPr is not None else None
    if el is None:
        return {"fmt": None, "start": None}
    fmt = el.get(elm("fmt"))
    start = el.get(elm("start"))
    start_i = None
    if start is not None:
        try:
            start_i = int(start)
        except ValueError:
            start_i = None
    return {"fmt": fmt, "start": start_i}


def document_has_toc_field(doc: Document) -> bool:
    body = doc.element.body
    for instr in body.iter(elm("instrText")):
        text = instr.text or "".join(instr.itertext())
        if text and re.search(r"\bTOC\b", text.upper()):
            return True
    for fld in body.iter(elm("fldSimple")):
        instr = fld.get(elm("instr")) or ""
        if re.search(r"\bTOC\b", instr.upper()):
            return True
    return False


def paragraph_section_indices(doc: Document) -> list[int]:
    """每个 doc.paragraphs[i] 所属节号（0-based）。只按正文段落上的 sectPr 计数。"""
    indices = []
    idx = 0
    for p in doc.paragraphs:
        indices.append(idx)
        pPr = p._p.pPr
        if pPr is not None and pPr.find(elm("sectPr")) is not None:
            idx += 1
    return indices


def first_paragraph_of_section(doc: Document, section_index_0: int) -> Optional[tuple[int, Paragraph]]:
    idxs = paragraph_section_indices(doc)
    for i, s in enumerate(idxs):
        if s == section_index_0:
            return i, doc.paragraphs[i]
    return None


# ---------- 段落分区 ----------

SPECIAL_HEADINGS = (
    "摘要", "目录", "目 录", "Abstract", "ABSTRACT",
    "参考文献", "致谢", "附录", "Key words", "Keywords",
)


def is_special_heading(text: str) -> bool:
    t = (text or "").strip()
    if t in SPECIAL_HEADINGS:
        return True
    for s in ("参考文献", "致谢", "附录", "摘要", "目录"):
        if t.startswith(s):
            return True
    return False


def classify_regions(doc: Document) -> list[str]:
    regions = []
    region = "cover"
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        lvl = heading_level(p)
        # 参考文献等必须先于「1 级标题即正文」判断，避免被标成 body
        # 手工目录里的「第1章…1」「参考文献…4」必须留在 toc，不能切到 body/refs
        if looks_like_toc_entry(text) and region in ("toc", "cover", "abstract"):
            if region != "toc" and (text.startswith("第") or text.startswith("附录")):
                pass  # 还没进入目录就出现带点线的行，仍不切换
        elif text.startswith("参考文献") and not looks_like_toc_entry(text):
            region = "refs"
        elif (text.startswith("摘要") or text in ("Abstract", "ABSTRACT")) and not looks_like_toc_entry(text):
            region = "abstract"
        elif text.startswith("目录") or text in ("目 录",):
            region = "toc"
        elif lvl == 1 and not is_special_heading(text) and not looks_like_toc_entry(text):
            region = "body"
        elif (
            CHAPTER_RE.match(text)
            and not is_special_heading(text)
            and not looks_like_toc_entry(text)
            and len(text) < 40
        ):
            region = "body"
        regions.append(region)
    return regions


def is_caption(text: str) -> Optional[str]:
    t = (text or "").strip()
    if FIG_CAPTION_RE.match(t):
        return "figure"
    if TBL_CAPTION_RE.match(t):
        return "table"
    return None


def representative_size(paragraph: Paragraph, doc: Document) -> Optional[float]:
    sizes = []
    for run in paragraph.runs:
        if not (run.text or "").strip():
            continue
        fmt = resolve_run_format(run, paragraph, doc)
        if fmt["size_pt"] is not None:
            sizes.append(fmt["size_pt"])
    if sizes:
        return sizes[0]
    return None


# ---------- 各项检查 ----------

def check_margins(doc: Document, rules: dict) -> list[Finding]:
    findings = []
    page = rules.get("page") or {}
    expected = page.get("margins_cm") or {}
    tol = float(page.get("tolerance_cm", 0.05))
    if not expected:
        return findings
    for i, section in enumerate(doc.sections, start=1):
        actual = section_margins_cm(section)
        for side in ("top", "bottom", "left", "right"):
            exp = expected.get(side)
            act = actual.get(side)
            if exp is None or act is None:
                continue
            if abs(act - float(exp)) > tol:
                findings.append(Finding(
                    key=f"margin:{i}:{side}",
                    category="margin",
                    message=(
                        f"【页边距】第 {i} 节{ {'top':'上','bottom':'下','left':'左','right':'右'}[side] }"
                        f"边距为 {act:.2f} cm，规范要求 {float(exp):.2f} cm"
                        f"（公差 {tol} cm）。"
                    ),
                    section=i,
                    side=side,
                ))
    return findings


def _body_like(region: str) -> bool:
    return region in ("body", "abstract")


def check_body_font_and_spacing(doc: Document, rules: dict, regions: list[str]) -> list[Finding]:
    findings = []
    body = rules.get("body") or {}
    font_cn = body.get("font_cn")
    font_en = body.get("font_en")
    size_pt = body.get("size_pt")
    size_tol = float(body.get("size_tolerance_pt", 0.1))
    line_sp = body.get("line_spacing")
    line_tol = float(body.get("line_spacing_tolerance", 0.05))
    indent_chars = body.get("first_line_indent_chars")
    indent_tol = float(body.get("indent_tolerance_chars", 0.3))

    for i, p in enumerate(doc.paragraphs):
        region = regions[i]
        text = (p.text or "").strip()
        if not text:
            continue
        if not _body_like(region):
            continue
        if heading_level(p) is not None:
            continue
        if is_caption(text):
            continue
        # 摘要、Abstract 标题本身跳过
        if text in ("摘要", "Abstract", "ABSTRACT", "关键词", "Key words", "Keywords") or text.startswith("关键词") or text.startswith("Key words") or text.startswith("Keywords"):
            continue

        # 字体 / 字号：按 run 检查，同一段同一类问题只报一次
        font_cn_wrong = None
        font_en_wrong = None
        size_wrong = None
        for run in p.runs:
            t = run.text or ""
            if not t.strip():
                continue
            fmt = resolve_run_format(run, p, doc)
            has_cjk = bool(CJK_RE.search(t))
            has_latin = bool(LATIN_RE.search(t))
            if has_cjk and font_cn and fmt["eastAsia"] and fmt["eastAsia"] != font_cn:
                font_cn_wrong = fmt["eastAsia"]
            if has_latin and font_en and fmt["ascii"] and fmt["ascii"] != font_en:
                font_en_wrong = fmt["ascii"]
            if size_pt is not None and fmt["size_pt"] is not None:
                if abs(fmt["size_pt"] - float(size_pt)) > size_tol:
                    size_wrong = fmt["size_pt"]
        if font_cn_wrong:
            findings.append(Finding(
                key=f"font_cn:{i}",
                category="font_cn",
                message=f"【字体】正文中文字体为「{font_cn_wrong}」，规范要求「{font_cn}」。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))
        if font_en_wrong:
            findings.append(Finding(
                key=f"font_en:{i}",
                category="font_en",
                message=f"【字体】正文西文字体为「{font_en_wrong}」，规范要求「{font_en}」。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))
        if size_wrong is not None:
            findings.append(Finding(
                key=f"font_size:{i}",
                category="font_size",
                message=f"【字号】正文字号为 {size_wrong:g} 磅，规范要求 {float(size_pt):g} 磅。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))

        if line_sp is not None:
            actual_ls = paragraph_line_spacing(p, doc)
            if actual_ls is not None and abs(actual_ls - float(line_sp)) > line_tol:
                findings.append(Finding(
                    key=f"line_spacing:{i}",
                    category="line_spacing",
                    message=f"【行距】正文行距为 {actual_ls:g} 倍，规范要求 {float(line_sp):g} 倍。",
                    paragraph_text=text,
                    paragraph_index=i,
                    anchor=text[:40],
                ))

        if indent_chars is not None:
            sz = representative_size(p, doc) or (float(size_pt) if size_pt else 12.0)
            actual_ind = paragraph_first_indent_chars(p, sz)
            if actual_ind is not None and abs(actual_ind - float(indent_chars)) > indent_tol:
                findings.append(Finding(
                    key=f"indent:{i}",
                    category="indent",
                    message=(
                        f"【首行缩进】正文首行缩进约为 {actual_ind:.1f} 字符，"
                        f"规范要求 {float(indent_chars):g} 字符。"
                    ),
                    paragraph_text=text,
                    paragraph_index=i,
                    anchor=text[:40],
                ))
    return findings


def check_headings(doc: Document, rules: dict, regions: list[str]) -> list[Finding]:
    findings = []
    specs = {int(h["level"]): h for h in (rules.get("headings") or []) if "level" in h}
    if not specs:
        return findings
    size_tol = 0.1
    # 收集各层标题以便查编号连续性
    collected = {lvl: [] for lvl in specs}  # list of (index, text, number)

    for i, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if not text:
            continue
        lvl = heading_level(p)
        if lvl is None or lvl not in specs:
            continue
        if is_special_heading(text):
            continue
        # 封面里可能有「标题」样式，只在 body 检查
        if regions[i] not in ("body",) and lvl >= 1:
            if not CHAPTER_RE.match(text) and lvl == 1:
                continue
        spec = specs[lvl]
        # 有效格式取该段第一个非空 run，若加粗在样式上也能 resolve
        fmt_agg = {"eastAsia": None, "size_pt": None, "bold": None}
        for run in p.runs:
            if not (run.text or "").strip():
                continue
            fmt = resolve_run_format(run, p, doc)
            if fmt_agg["eastAsia"] is None:
                fmt_agg["eastAsia"] = fmt["eastAsia"]
            if fmt_agg["size_pt"] is None:
                fmt_agg["size_pt"] = fmt["size_pt"]
            # 只要有一个非空 run 的有效加粗为 False，就认为未加粗（整段应加粗）
            if fmt["bold"] is not None:
                if fmt_agg["bold"] is None:
                    fmt_agg["bold"] = fmt["bold"]
                else:
                    fmt_agg["bold"] = fmt_agg["bold"] and fmt["bold"]

        font_cn = spec.get("font_cn")
        if font_cn and fmt_agg["eastAsia"] and fmt_agg["eastAsia"] != font_cn:
            findings.append(Finding(
                key=f"heading_font:{lvl}:{i}",
                category="heading_font",
                message=(
                    f"【标题字体】{lvl} 级标题「{text[:30]}」中文字体为「{fmt_agg['eastAsia']}」，"
                    f"规范要求「{font_cn}」。"
                ),
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))
        size_pt = spec.get("size_pt")
        if size_pt is not None and fmt_agg["size_pt"] is not None:
            if abs(fmt_agg["size_pt"] - float(size_pt)) > size_tol:
                findings.append(Finding(
                    key=f"heading_size:{lvl}:{i}",
                    category="heading_size",
                    message=(
                        f"【标题字号】{lvl} 级标题「{text[:30]}」字号为 {fmt_agg['size_pt']:g} 磅，"
                        f"规范要求 {float(size_pt):g} 磅。"
                    ),
                    paragraph_text=text,
                    paragraph_index=i,
                    anchor=text[:40],
                ))
        if spec.get("bold") is True and fmt_agg["bold"] is False:
            findings.append(Finding(
                key=f"heading_bold:{lvl}:{i}",
                category="heading_bold",
                message=f"【标题加粗】{lvl} 级标题「{text[:30]}」未加粗，规范要求加粗。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))

        kind = spec.get("numbering_kind")
        number = None
        if kind == "cn_or_digit_chapter":
            m = CHAPTER_RE.match(text)
            if not m:
                findings.append(Finding(
                    key=f"heading_number_format:{lvl}:{i}",
                    category="heading_number_format",
                    message=f"【标题编号】1 级标题「{text[:30]}」不符合「第X章」格式。",
                    paragraph_text=text,
                    paragraph_index=i,
                    anchor=text[:40],
                ))
            else:
                number = cn_or_digit_to_int(m.group(1))
        elif kind == "dotted":
            m = DOTTED_RE.match(text + (" " if not text.endswith(" ") else ""))
            # 也允许标题就是 "1.1" 后面直接中文无空格
            if m is None:
                m = re.match(r"^(\d+(?:\.\d+)+)", text)
            if not m:
                findings.append(Finding(
                    key=f"heading_number_format:{lvl}:{i}",
                    category="heading_number_format",
                    message=f"【标题编号】{lvl} 级标题「{text[:30]}」不符合「X.Y」数字编号格式。",
                    paragraph_text=text,
                    paragraph_index=i,
                    anchor=text[:40],
                ))
            else:
                number = m.group(1)
        collected.setdefault(lvl, []).append((i, text, number, p))

    # 编号连续性：每一级单独看。1 级按整数递增；dotted 按同前缀下最后一段递增。
    for lvl, items in collected.items():
        spec = specs.get(lvl) or {}
        kind = spec.get("numbering_kind")
        if kind == "cn_or_digit_chapter":
            nums = [(it[0], it[1], it[2]) for it in items if it[2] is not None]
            for prev, cur in zip(nums, nums[1:]):
                if cur[2] != prev[2] + 1:
                    findings.append(Finding(
                        key=f"heading_number_seq:{lvl}:{cur[0]}",
                        category="heading_number_seq",
                        message=(
                            f"【标题编号】章号不连续：在「{prev[1][:20]}」（{prev[2]}）之后"
                            f"出现「{cur[1][:20]}」（{cur[2]}），缺 {prev[2] + 1}。"
                        ),
                        paragraph_text=cur[1],
                        paragraph_index=cur[0],
                        anchor=cur[1][:40],
                    ))
        elif kind == "dotted":
            # 按父前缀分组，最后一位应 1,2,3...
            groups: dict[str, list] = {}
            for it in items:
                num = it[2]
                if not num:
                    continue
                parts = str(num).split(".")
                parent = ".".join(parts[:-1])
                try:
                    last = int(parts[-1])
                except ValueError:
                    continue
                groups.setdefault(parent, []).append((it[0], it[1], last))
            for parent, seq in groups.items():
                for prev, cur in zip(seq, seq[1:]):
                    if cur[2] != prev[2] + 1:
                        findings.append(Finding(
                            key=f"heading_number_seq:{lvl}:{cur[0]}",
                            category="heading_number_seq",
                            message=(
                                f"【标题编号】{lvl} 级编号不连续：在「{prev[1][:20]}」之后"
                                f"出现「{cur[1][:20]}」，缺 {parent + ('.' if parent else '')}{prev[2] + 1}。"
                            ),
                            paragraph_text=cur[1],
                            paragraph_index=cur[0],
                            anchor=cur[1][:40],
                        ))
    return findings


def _caption_font_and_size(p: Paragraph, doc: Document) -> dict:
    fmt_agg = {"eastAsia": None, "size_pt": None}
    for run in p.runs:
        if not (run.text or "").strip():
            continue
        fmt = resolve_run_format(run, p, doc)
        if fmt_agg["eastAsia"] is None:
            fmt_agg["eastAsia"] = fmt["eastAsia"]
        if fmt_agg["size_pt"] is None:
            fmt_agg["size_pt"] = fmt["size_pt"]
    return fmt_agg


def check_captions(doc: Document, rules: dict) -> list[Finding]:
    findings = []
    cap = rules.get("captions") or {}
    if not cap:
        return findings
    font_cn = cap.get("font_cn")
    size_pt = cap.get("size_pt")
    size_tol = float(cap.get("size_tolerance_pt", 0.1))
    number_format = cap.get("number_format", "arabic")
    check_seq = cap.get("check_sequence", True)

    figures = []  # (i, text, raw_num, parsed_int or None, format_ok)
    tables = []

    for i, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if not text:
            continue
        kind = is_caption(text)
        if not kind:
            continue
        m = FIG_CAPTION_RE.match(text) if kind == "figure" else TBL_CAPTION_RE.match(text)
        raw = m.group(1) if m else ""
        format_ok = is_arabic_number(raw) if number_format == "arabic" else True
        parsed = cn_or_digit_to_int(raw) if raw else None
        if kind == "figure":
            figures.append((i, text, raw, parsed, format_ok, p))
        else:
            tables.append((i, text, raw, parsed, format_ok, p))

        if number_format == "arabic" and raw and not format_ok:
            prefix = "图" if kind == "figure" else "表"
            findings.append(Finding(
                key=f"caption_format:{kind}:{i}",
                category="caption_format",
                message=f"【题注格式】「{text[:30]}」编号不是阿拉伯数字，规范要求「{prefix}1」这类格式。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))

        fmt = _caption_font_and_size(p, doc)
        if font_cn and fmt["eastAsia"] and fmt["eastAsia"] != font_cn:
            findings.append(Finding(
                key=f"caption_font:{kind}:{i}",
                category="caption_font",
                message=f"【题注字体】「{text[:30]}」中文字体为「{fmt['eastAsia']}」，规范要求「{font_cn}」。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))
        if size_pt is not None and fmt["size_pt"] is not None:
            if abs(fmt["size_pt"] - float(size_pt)) > size_tol:
                findings.append(Finding(
                    key=f"caption_size:{kind}:{i}",
                    category="caption_size",
                    message=(
                        f"【题注字号】「{text[:30]}」字号为 {fmt['size_pt']:g} 磅，"
                        f"规范要求 {float(size_pt):g} 磅。"
                    ),
                    paragraph_text=text,
                    paragraph_index=i,
                    anchor=text[:40],
                ))

    def seq_findings(items, kind):
        if not check_seq:
            return
        # 只对格式正确、能解析的编号查连续性，避免「表一」被再报一次跳号
        valid = [(it[0], it[1], it[3]) for it in items if it[4] and it[3] is not None]
        if not valid:
            return
        for prev, cur in zip(valid, valid[1:]):
            if cur[2] != prev[2] + 1:
                missing = prev[2] + 1
                findings.append(Finding(
                    key=f"caption_seq:{kind}:{cur[0]}",
                    category="caption_seq",
                    message=(
                        f"【题注编号】{'图' if kind=='figure' else '表'}题号不连续："
                        f"在 {prev[2]} 之后出现 {cur[2]}，缺 {missing}。"
                    ),
                    paragraph_text=cur[1],
                    paragraph_index=cur[0],
                    anchor=cur[1][:40],
                ))
                # 同一类题注只报第一处跳号，避免一条跳号连带后面全部再报
                break

    seq_findings(figures, "figure")
    seq_findings(tables, "table")
    return findings


def check_headers_and_page_numbers(doc: Document, rules: dict, regions: list[str]) -> list[Finding]:
    findings = []
    hf = rules.get("header_footer") or {}
    if not hf:
        return findings
    body_header = hf.get("body_header_text")
    body_pn_required = hf.get("body_page_numbers_required", True)
    body_fmt = hf.get("body_page_number_format")  # decimal
    body_restart = hf.get("body_page_number_restart")
    front_fmt = hf.get("front_page_number_format")

    idxs = paragraph_section_indices(doc)
    # 节角色：若该节有 body 区段落，视为正文节；否则若全是 cover/abstract/toc，视为前置节
    n_sections = len(doc.sections)
    roles = []
    for s in range(n_sections):
        para_regions = [regions[i] for i, sec in enumerate(idxs) if sec == s]
        if "body" in para_regions or "refs" in para_regions:
            roles.append("body")
        else:
            roles.append("front")

    for i, section in enumerate(doc.sections):
        role = roles[i] if i < len(roles) else "front"
        sec_no = i + 1
        try:
            header = section.header
            footer = section.footer
        except Exception:
            header, footer = None, None

        if role == "body" and body_header:
            text = header_footer_text(header) if header is not None else ""
            if body_header not in (text or "").replace(" ", ""):
                # 也允许带空格的原文直接包含
                if body_header not in (text or ""):
                    findings.append(Finding(
                        key=f"header:{sec_no}",
                        category="header",
                        message=(
                            f"【页眉】第 {sec_no} 节（正文）页眉为「{(text or '').strip()[:30] or '（空）'}」，"
                            f"规范要求含「{body_header}」。"
                        ),
                        section=sec_no,
                    ))

        if role == "body" and body_pn_required:
            footer_el = footer._element if footer is not None else None
            header_el = header._element if header is not None else None
            has_pn = has_page_field(footer_el) or has_page_field(header_el)
            if not has_pn:
                findings.append(Finding(
                    key=f"page_number_missing:{sec_no}",
                    category="page_number_missing",
                    message=f"【页码】第 {sec_no} 节（正文）页眉页脚未发现 PAGE 域，规范要求正文有页码。",
                    section=sec_no,
                ))

        pg = section_pg_num_type(section)
        if role == "body" and body_restart is not None:
            if pg["start"] != int(body_restart):
                findings.append(Finding(
                    key=f"page_number_restart:{sec_no}",
                    category="page_number_restart",
                    message=(
                        f"【页码分节】第 {sec_no} 节（正文）页码起始为"
                        f"{'未设置' if pg['start'] is None else pg['start']}，"
                        f"规范要求从 {int(body_restart)} 重新起编。"
                    ),
                    section=sec_no,
                ))
        # 仅当已设置 fmt 且与规范不符时才报，缺省不报，以免与「无页码」叠出误报
        if role == "body" and body_fmt and pg["fmt"] is not None and pg["fmt"] != body_fmt:
            findings.append(Finding(
                key=f"page_number_format:{sec_no}",
                category="page_number_format",
                message=f"【页码】第 {sec_no} 节页码格式为 {pg['fmt']}，规范要求 {body_fmt}。",
                section=sec_no,
            ))
        if role == "front" and front_fmt and pg["fmt"] is not None and pg["fmt"] != front_fmt:
            findings.append(Finding(
                key=f"page_number_format:{sec_no}",
                category="page_number_format",
                message=f"【页码】第 {sec_no} 节（前置）页码格式为 {pg['fmt']}，规范要求 {front_fmt}。",
                section=sec_no,
            ))
    return findings


def check_toc(doc: Document, rules: dict, regions: list[str]) -> list[Finding]:
    findings = []
    toc = rules.get("toc") or {}
    if not toc.get("required") and not toc.get("must_be_automatic"):
        return findings
    has_field = document_has_toc_field(doc)
    has_toc_heading = any(
        (p.text or "").strip().startswith("目录") or (p.text or "").strip() in ("目 录",)
        for p in doc.paragraphs
    )
    if toc.get("must_be_automatic", True) or toc.get("required"):
        if not has_field:
            # 锚到目录标题段
            idx, text = 0, "目录"
            for i, p in enumerate(doc.paragraphs):
                t = (p.text or "").strip()
                if t.startswith("目录") or t in ("目 录",):
                    idx, text = i, t
                    break
            findings.append(Finding(
                key="toc:not_automatic",
                category="toc",
                message="【目录】未发现自动目录域（TOC 域）。规范要求使用 Word 自动目录，而不是手工敲出来的目录文字。",
                paragraph_text=text,
                paragraph_index=idx,
                anchor=text[:40],
            ))
    return findings


def check_references(doc: Document, rules: dict, regions: list[str]) -> list[Finding]:
    findings = []
    ref_rules = rules.get("references") or {}
    if not ref_rules:
        return findings
    require_year = ref_rules.get("require_year", True)
    check_seq = ref_rules.get("check_sequence", True)
    entries = []
    for i, p in enumerate(doc.paragraphs):
        if regions[i] != "refs":
            # 标题「参考文献」本身 region 已切到 refs，条目也是
            continue
        text = (p.text or "").strip()
        if not text or text.startswith("参考文献"):
            continue
        m = REF_RE.match(text)
        if not m:
            continue
        num = int(m.group(1))
        rest = m.group(2)
        entries.append((i, text, num, rest))
        if require_year and not YEAR_RE.search(text):
            findings.append(Finding(
                key=f"reference_year:{i}",
                category="reference_year",
                message=f"【参考文献】「{text[:40]}」未发现四位年份（19xx 或 20xx）。",
                paragraph_text=text,
                paragraph_index=i,
                anchor=text[:40],
            ))
    if check_seq and entries:
        for prev, cur in zip(entries, entries[1:]):
            if cur[2] != prev[2] + 1:
                findings.append(Finding(
                    key=f"reference_seq:{cur[0]}",
                    category="reference_seq",
                    message=f"【参考文献】编号不连续：在 [{prev[2]}] 之后出现 [{cur[2]}]，缺 [{prev[2] + 1}]。",
                    paragraph_text=cur[1],
                    paragraph_index=cur[0],
                    anchor=cur[1][:40],
                ))
                break
    return findings


def run_checks(doc: Document, rules: dict) -> list[Finding]:
    regions = classify_regions(doc)
    findings: list[Finding] = []
    findings.extend(check_margins(doc, rules))
    findings.extend(check_body_font_and_spacing(doc, rules, regions))
    findings.extend(check_headings(doc, rules, regions))
    findings.extend(check_captions(doc, rules))
    findings.extend(check_headers_and_page_numbers(doc, rules, regions))
    findings.extend(check_toc(doc, rules, regions))
    findings.extend(check_references(doc, rules, regions))
    return findings


def _ensure_run(p: Paragraph):
    if p.runs:
        return p.runs
    run = p.add_run("")
    return [run]


ANCHOR_NOTE = "（检查工具添加：原文没有可锚段落，批注挂在此处。）"


def _ensure_anchor_paragraph(doc: Document) -> tuple[Paragraph, bool]:
    """返回可用于挂批注的段落。若文档原本没有任何段落，则添加一段说明（返回 added=True）。"""
    if doc.paragraphs:
        return doc.paragraphs[0], False
    p = doc.add_paragraph()
    p.add_run(ANCHOR_NOTE)
    return p, True


def attach_comments(doc: Document, findings: list[Finding], author: str, initials: str) -> tuple[int, str]:
    """把每条 finding 写成 Word 批注。节级问题锚到该节首段。

    返回 (成功条数, 说明)。文档没有可锚段落时，会添加一段说明文字用于挂载批注，
    以便「写出的问题数」与「写入的批注数」一致。
    """
    attached = 0
    added_anchor = False
    fail_notes = []
    fallback_p = None
    for f in findings:
        p = None
        if f.paragraph_index is not None and 0 <= f.paragraph_index < len(doc.paragraphs):
            p = doc.paragraphs[f.paragraph_index]
        elif f.section is not None:
            got = first_paragraph_of_section(doc, f.section - 1)
            if got:
                p = got[1]
                f.paragraph_index = got[0]
                f.paragraph_text = (p.text or "")[:200]
        if p is None:
            if fallback_p is None:
                fallback_p, added = _ensure_anchor_paragraph(doc)
                added_anchor = added_anchor or added
            p = fallback_p
            if f.paragraph_index is None:
                try:
                    f.paragraph_index = list(doc.paragraphs).index(p)
                except ValueError:
                    f.paragraph_index = 0
        runs = _ensure_run(p)
        # 空 run 无法挂批注，补一个零宽字符
        if not any((r.text or "") for r in runs):
            runs[0].text = "​"
        try:
            doc.add_comment(runs, text=f.message, author=author, initials=initials)
            attached += 1
        except Exception as e:
            f.message = f.message + f"（写批注失败：{type(e).__name__}）"
            fail_notes.append(str(e))
    note_parts = []
    if added_anchor:
        note_parts.append("原文没有可锚段落，已添加一段说明文字用于挂载批注。")
    if fail_notes:
        note_parts.append(f"{len(fail_notes)} 条批注写入失败。")
    return attached, "".join(note_parts)


def rules_have_checks(rules: dict) -> bool:
    """规则里是否启用了任何可机读检查项。"""
    return any(
        rules.get(k)
        for k in ("page", "body", "headings", "captions", "header_footer", "toc", "references")
    )


def write_summary(
    path: Path,
    rules: dict,
    findings: list[Finding],
    attached: int,
    *,
    rules_empty: bool = False,
    attach_note: str = "",
) -> None:
    school = rules.get("school_name") or "（未写校名）"
    title = rules.get("document_title") or ""
    disclaimer = rules.get("disclaimer") or ""
    pending = rules.get("pending") or []
    lines = []
    lines.append("# 毕业论文格式自查汇总")
    lines.append("")
    lines.append(f"所用规则：{school} · {title}")
    if disclaimer:
        lines.append(f"> {disclaimer}")
    lines.append("")
    lines.append("数据去向：检查在本机完成，不调用外部接口，不上传文档，不用 GPU。")
    lines.append("")
    lines.append("本工具只检查规则文件里启用的可机读项，不担保覆盖任何学校的全部条款。")
    if rules_empty:
        lines.append("规则为空，未启用任何检查项，未执行格式检查。这不表示论文格式没有问题。")
        lines.append("")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    lines.append(f"本次共写出 {len(findings)} 条问题（成功写入 Word 批注 {attached} 条）。")
    if attach_note:
        lines.append(attach_note)
    if findings and attached != len(findings):
        lines.append(
            f"写出的问题数（{len(findings)}）与写入的批注数（{attached}）不一致。"
            "未能写入的条目已在下方标明原因。"
        )
    lines.append("")
    if pending:
        lines.append("## 待确认（规则中标明、本工具不下结论）")
        for item in pending:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## 问题列表")
    if not findings:
        lines.append("未发现与规则不符的可机读问题。这不表示论文格式已完全符合学院要求。")
    else:
        by_cat = {}
        for f in findings:
            by_cat.setdefault(f.category, []).append(f)
        for cat, items in by_cat.items():
            lines.append(f"### {cat}（{len(items)}）")
            for f in items:
                loc = ""
                if f.paragraph_index is not None:
                    loc = f"  （段落 {f.paragraph_index}）"
                elif f.section is not None:
                    loc = f"  （第 {f.section} 节）"
                lines.append(f"- {f.message}{loc}")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="按结构化规则检查毕业论文 docx，并把问题写成 Word 批注（本机、无外部接口）。"
    )
    parser.add_argument("--rules", required=True, help="结构化规则 JSON 路径")
    parser.add_argument("--input", required=True, help="待检查的 docx")
    parser.add_argument("--output", required=True, help="写出的带批注 docx")
    parser.add_argument("--summary", required=True, help="一页问题汇总 Markdown")
    parser.add_argument("--findings", help="可选，把检查结果写成 JSON")
    parser.add_argument("--author", default="毕业论文格式自查", help="Word 批注作者名")
    parser.add_argument("--initials", default="查")
    args = parser.parse_args(argv)

    rules_path = Path(args.rules)
    input_path = Path(args.input)
    output_path = Path(args.output)
    summary_path = Path(args.summary)

    if not rules_path.is_file():
        print(f"找不到规则文件：{rules_path}", file=sys.stderr)
        return 2
    if not input_path.is_file():
        print(f"找不到输入文档：{input_path}", file=sys.stderr)
        return 2

    try:
        rules = load_rules(rules_path)
    except json.JSONDecodeError:
        print(f"规则文件不是合法的 JSON：{rules_path}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"{e}：{rules_path}", file=sys.stderr)
        return 2
    except OSError:
        print(f"无法读取规则文件：{rules_path}", file=sys.stderr)
        return 2

    try:
        doc = Document(str(input_path))
    except Exception:
        print(f"无法打开输入文档，请提供完好的 Word .docx 文件：{input_path}", file=sys.stderr)
        return 2

    rules_empty = not rules_have_checks(rules)
    if rules_empty:
        findings = []
        attached = 0
        attach_note = ""
    else:
        findings = run_checks(doc, rules)
        attached, attach_note = attach_comments(
            doc, findings, author=args.author, initials=args.initials
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(str(output_path))
    except Exception:
        print(f"无法写出带批注文档：{output_path}", file=sys.stderr)
        return 2
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_summary(
        summary_path, rules, findings, attached,
        rules_empty=rules_empty, attach_note=attach_note,
    )
    payload = {
        "rules": str(rules_path),
        "input": str(input_path),
        "output": str(output_path),
        "summary": str(summary_path),
        "disclaimer": rules.get("disclaimer"),
        "school_name": rules.get("school_name"),
        "n_findings": len(findings),
        "n_comments_written": attached,
        "rules_empty": rules_empty,
        "attach_note": attach_note,
        "data_stays_local": True,
        "external_calls": [],
        "findings": [f.to_dict() for f in findings],
    }
    if args.findings:
        fp = Path(args.findings)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if rules_empty:
        print("规则为空，未启用任何检查项，未执行格式检查。")
    else:
        print(f"检查完成：{len(findings)} 条问题，写入批注 {attached} 条。")
        if attach_note:
            print(attach_note)
    print(f"带批注文档：{output_path}")
    print(f"汇总：{summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

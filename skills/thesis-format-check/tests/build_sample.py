#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成带 20 处已知错误的虚构毕业论文样例。内容全部虚构，不是真实学生论文。

本脚本只负责造样例和公开错误清单，不运行检查。
清单与 docx 须在检查之前冻结。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Twips, Emu
from docx.oxml.ns import nsmap

# ---------------------------------------------------------------------------
# 公开的 20 处埋错（测试前固定）。id 与 match 条件供对照，检查脚本本身不读本清单。
# ---------------------------------------------------------------------------
GOLD_ERRORS = [
    {
        "id": "E01",
        "category": "margin",
        "description": "正文节（第 2 节）左边距为 2.54 cm，规范要求 3.17 cm。",
        "match": {"category": "margin", "section": 2, "side": "left"},
    },
    {
        "id": "E02",
        "category": "margin",
        "description": "正文节（第 2 节）上边距为 2.00 cm，规范要求 2.54 cm。",
        "match": {"category": "margin", "section": 2, "side": "top"},
    },
    {
        "id": "E03",
        "category": "margin",
        "description": "前置节（第 1 节）右边距为 2.00 cm，规范要求 3.17 cm。",
        "match": {"category": "margin", "section": 1, "side": "right"},
    },
    {
        "id": "E04",
        "category": "font_cn",
        "description": "一段正文中文字体为楷体，规范要求宋体。",
        "match": {"category": "font_cn", "anchor": "【E04】"},
    },
    {
        "id": "E05",
        "category": "font_size",
        "description": "一段正文字号为 14 磅，规范要求 12 磅。",
        "match": {"category": "font_size", "anchor": "【E05】"},
    },
    {
        "id": "E06",
        "category": "heading_font",
        "description": "「第1章 绪论」中文字体为宋体，规范要求黑体。",
        "match": {"category": "heading_font", "anchor": "第1章 绪论"},
    },
    {
        "id": "E07",
        "category": "heading_size",
        "description": "「第1章 绪论」字号为 14 磅，规范要求 16 磅。",
        "match": {"category": "heading_size", "anchor": "第1章 绪论"},
    },
    {
        "id": "E08",
        "category": "heading_bold",
        "description": "二级标题「1.1 研究背景」未加粗，规范要求加粗。",
        "match": {"category": "heading_bold", "anchor": "1.1 研究背景"},
    },
    {
        "id": "E09",
        "category": "line_spacing",
        "description": "一段正文为单倍行距，规范要求 1.5 倍。",
        "match": {"category": "line_spacing", "anchor": "【E09】"},
    },
    {
        "id": "E10",
        "category": "indent",
        "description": "一段正文无首行缩进，规范要求 2 字符。",
        "match": {"category": "indent", "anchor": "【E10】"},
    },
    {
        "id": "E11",
        "category": "heading_number_seq",
        "description": "章号从「第二章 方法」跳到「第4章 结论」，缺第三章。",
        "match": {"category": "heading_number_seq", "anchor": "第4章 结论"},
    },
    {
        "id": "E12",
        "category": "heading_number_seq",
        "description": "二级标题从「1.1 研究背景」跳到「1.3 研究意义」，缺 1.2。",
        "match": {"category": "heading_number_seq", "anchor": "1.3 研究意义"},
    },
    {
        "id": "E13",
        "category": "caption_seq",
        "description": "图题号从 图2 跳到 图4，缺 图3。",
        "match": {"category": "caption_seq", "anchor": "图 4"},
    },
    {
        "id": "E14",
        "category": "caption_format",
        "description": "表题写成「表一」，规范要求阿拉伯数字「表1」。",
        "match": {"category": "caption_format", "anchor": "表一"},
    },
    {
        "id": "E15",
        "category": "caption_size",
        "description": "「图 5」题注字号为 12 磅，规范要求 10.5 磅。",
        "match": {"category": "caption_size", "anchor": "图 5"},
    },
    {
        "id": "E16",
        "category": "page_number_missing",
        "description": "正文节页眉页脚没有 PAGE 域。",
        "match": {"category": "page_number_missing", "section": 2},
    },
    {
        "id": "E17",
        "category": "page_number_restart",
        "description": "正文节页码未从 1 重新起编。",
        "match": {"category": "page_number_restart", "section": 2},
    },
    {
        "id": "E18",
        "category": "header",
        "description": "正文节页眉不是规定文字「示例大学本科毕业论文」。",
        "match": {"category": "header", "section": 2},
    },
    {
        "id": "E19",
        "category": "toc",
        "description": "目录是手工文字，不是 Word 自动目录域。",
        "match": {"category": "toc", "anchor": "目录"},
    },
    {
        "id": "E20",
        "category": "reference_year",
        "description": "参考文献 [2] 缺少四位年份。",
        "match": {"category": "reference_year", "anchor": "【E20】"},
    },
]


def set_run_font(run, east_asia: str, ascii_font: str, size_pt: float, bold=None):
    run.font.size = Pt(size_pt)
    run.font.name = ascii_font
    if bold is not None:
        run.font.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), ascii_font)
    rFonts.set(qn("w:hAnsi"), ascii_font)
    rFonts.set(qn("w:eastAsia"), east_asia)
    rFonts.set(qn("w:cs"), ascii_font)
    if bold is not None:
        # 显式写 w:b，避免只靠 python-docx 布尔值被样式覆盖时含糊
        for tag in ("b", "bCs"):
            for old in rPr.findall(qn(f"w:{tag}")):
                rPr.remove(old)
        b = OxmlElement("w:b")
        b.set(qn("w:val"), "1" if bold else "0")
        rPr.append(b)


def set_para_spacing_indent(p, line_multiple: float, indent_chars: float, size_pt: float = 12.0):
    p.paragraph_format.line_spacing = line_multiple
    pPr = p._p.get_or_add_pPr()
    # 行距
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:line"), str(int(round(line_multiple * 240))))
    spacing.set(qn("w:lineRule"), "auto")
    # 首行缩进：同时写 firstLineChars 与 firstLine
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    if indent_chars and indent_chars > 0:
        ind.set(qn("w:firstLineChars"), str(int(round(indent_chars * 100))))
        twips = int(round(indent_chars * size_pt * 20))
        ind.set(qn("w:firstLine"), str(twips))
        if qn("w:hanging") in ind.attrib:
            del ind.attrib[qn("w:hanging")]
    else:
        ind.set(qn("w:firstLineChars"), "0")
        ind.set(qn("w:firstLine"), "0")


def add_text_para(
    doc,
    text: str,
    *,
    east_asia="宋体",
    ascii_font="Times New Roman",
    size_pt=12,
    bold=None,
    line=1.5,
    indent=2.0,
    align=None,
    style=None,
    space_after_pt=6,
    space_before_pt=0,
):
    p = doc.add_paragraph()
    if style:
        p.style = style
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after_pt)
    p.paragraph_format.space_before = Pt(space_before_pt)
    run = p.add_run(text)
    set_run_font(run, east_asia, ascii_font, size_pt, bold=bold)
    set_para_spacing_indent(p, line, indent, size_pt=size_pt)
    return p


def add_heading_para(
    doc,
    text: str,
    level: int,
    *,
    east_asia="黑体",
    ascii_font="Times New Roman",
    size_pt=16,
    bold=True,
    align=None,
):
    p = doc.add_paragraph(style=f"Heading {level}")
    if align is not None:
        p.alignment = align
    # 去掉样式可能自带的不同字体，全部写到 run 上
    p.clear()
    # heading 不要首行缩进
    run = p.add_run(text)
    set_run_font(run, east_asia, ascii_font, size_pt, bold=bold)
    set_para_spacing_indent(p, 1.5, 0, size_pt=size_pt)
    p.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    p.paragraph_format.space_after = Pt(8 if level == 1 else 6)
    return p


def set_section_page(section, *, top, bottom, left, right):
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(top)
    section.bottom_margin = Cm(bottom)
    section.left_margin = Cm(left)
    section.right_margin = Cm(right)


def set_pg_num_type(section, fmt: str, start=None):
    sectPr = section._sectPr
    for old in sectPr.findall(qn("w:pgNumType")):
        sectPr.remove(old)
    el = OxmlElement("w:pgNumType")
    el.set(qn("w:fmt"), fmt)
    if start is not None:
        el.set(qn("w:start"), str(start))
    sectPr.append(el)


def add_page_field(paragraph):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    # 占位显示
    run2_t = OxmlElement("w:t")
    run2_t.text = "1"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    r2 = OxmlElement("w:r")
    r2.append(instr)
    run._r.addnext(r2)
    r3 = OxmlElement("w:r")
    r3.append(fld_sep)
    r2.addnext(r3)
    r4 = OxmlElement("w:r")
    r4.append(run2_t)
    r3.addnext(r4)
    r5 = OxmlElement("w:r")
    r5.append(fld_end)
    r4.addnext(r5)


def shade_cell(cell, color="D9D9D9"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def add_placeholder_figure(doc, caption: str, *, cap_size=10.5, east_asia="宋体", height_cm=3.2, label="（示意图占位，虚构样例）"):
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(label)
    set_run_font(run, "宋体", "Times New Roman", 10.5, bold=False)
    shade_cell(cell)
    # 行高
    tr = table.rows[0]._tr
    trPr = tr.get_or_add_trPr()
    trHeight = OxmlElement("w:trHeight")
    trHeight.set(qn("w:val"), str(int(height_cm * 567)))  # twips approx, 1cm≈567 twips
    trHeight.set(qn("w:hRule"), "atLeast")
    trPr.append(trHeight)
    cap = add_text_para(
        doc, caption,
        east_asia=east_asia, ascii_font="Times New Roman",
        size_pt=cap_size, bold=False, line=1.5, indent=0,
        align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=10, space_before_pt=4,
    )
    return cap


def write_gold(out_json: Path, out_md: Path):
    payload = {
        "disclaimer": "本错误清单与样例文档是测试前公开、预先固定的。内容全部虚构，不来自真实学生论文，规则对照的是虚构示例规范。检查脚本不读取本清单。",
        "n_planted": len(GOLD_ERRORS),
        "sample_composition": {
            "document": "一份虚构的「示例大学」本科毕业论文短样（封面、摘要、手工目录、两章正文、图和表、参考文献）",
            "rules": "rules/example_rules.json（虚构示例规则）",
            "planted_errors": 20,
            "correct_controls": [
                "若干段宋体 12 磅、1.5 倍行距、首行缩进 2 字符的正文",
                "「第二章 方法」为黑体 16 磅加粗，章号连续到此（之后才跳号）",
                "二级标题「2.1 实验设计」黑体 14 磅加粗，编号正确",
                "图 1、图 2 题注为宋体 10.5 磅且编号连续",
                "参考文献 [1]、[3] 含年份且编号连续",
                "前置节页码为罗马数字并含 PAGE 域，页眉正确",
                "中文摘要、英文 Abstract 使用规范字体字号",
            ],
            "not_student_work": True,
            "fictional_school": True,
        },
        "errors": GOLD_ERRORS,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 预埋 20 处错误清单（测试前公开固定）",
        "",
        "> 本文档与 `gold_errors.json`、`sample_thesis.docx` 在检查跑次之前固定。",
        "> 样例内容全部虚构，不来自真实学生论文；对照的是虚构示例规则，不冒充真实学校规范。",
        "",
        "## 样本构成",
        "",
        "- 一份短篇虚构毕业论文 docx：封面、中英文摘要、手工目录、第1章（含图）、第二章（含表）、第4章（跳号）、参考文献。",
        "- 正确对照：若干规范正文段落、正确的「第二章」「2.1」、图 1 和图 2、参考文献 [1] 和 [3]、前置节罗马页码。",
        "- 故意埋入下面 20 处已知错误。段落中的【E04】等标记只用于对照本清单，不是论文内容。",
        "",
        "## 20 处埋错",
        "",
        "| 编号 | 类别 | 说明 |",
        "| --- | --- | --- |",
    ]
    for e in GOLD_ERRORS:
        lines.append(f"| {e['id']} | `{e['category']}` | {e['description']} |")
    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")


def build_docx(path: Path):
    doc = Document()

    # 默认样式：正文宋体 12 磅
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    rPr = normal.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), "宋体")

    # ---------- 第 1 节：前置（封面、摘要、目录）----------
    sec0 = doc.sections[0]
    # E03：右边距 2.00 cm；其余正确
    set_section_page(sec0, top=2.54, bottom=2.54, left=3.17, right=2.00)
    set_pg_num_type(sec0, "upperRoman", start=1)
    sec0.header.is_linked_to_previous = False
    sec0.footer.is_linked_to_previous = False
    hp = sec0.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run("示例大学本科毕业论文")
    set_run_font(hr, "宋体", "Times New Roman", 10.5, bold=False)
    fp = sec0.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_field(fp)

    # 封面
    add_text_para(
        doc, "示例大学（虚构）",
        east_asia="黑体", ascii_font="Times New Roman", size_pt=18, bold=True,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=6, space_before_pt=36,
    )
    add_text_para(
        doc, "本科毕业论文",
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=18,
    )
    add_text_para(
        doc, "面向格式检查的虚构样例论文",
        east_asia="黑体", ascii_font="Times New Roman", size_pt=22, bold=True,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=18,
    )
    add_text_para(
        doc,
        "说明：本文档是格式自查工具的公开测试样例。学校、作者、正文和参考文献全部虚构，"
        "不对应任何真实学校或学生。段落中的【E04】等标记仅用于对照预先公开的错误清单。",
        east_asia="宋体", ascii_font="Times New Roman", size_pt=10.5, bold=False,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=12,
    )
    # 分页到摘要
    p_break = doc.add_paragraph()
    run_b = p_break.add_run()
    run_b.add_break(WD_BREAK.PAGE)

    # 摘要（正确格式，作为对照）
    add_heading_like = add_text_para(
        doc, "摘要",
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=10, space_before_pt=6,
    )
    add_text_para(
        doc,
        "本文是一份用于演示毕业论文格式自查的虚构样例，讨论对象、数据和结论均为虚构。"
        "摘要本身按规范使用宋体、12 磅、1.5 倍行距和首行缩进 2 字符，作为正确对照，不埋错误。",
        east_asia="宋体", ascii_font="Times New Roman", size_pt=12, bold=False,
        line=1.5, indent=2.0,
    )
    add_text_para(
        doc, "关键词：格式自查；虚构样例；学位论文（以上关键词亦为虚构）",
        east_asia="宋体", ascii_font="Times New Roman", size_pt=12, bold=False,
        line=1.5, indent=0, space_after_pt=16,
    )
    add_text_para(
        doc, "Abstract",
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=10,
    )
    add_text_para(
        doc,
        "This fictitious sample thesis is written only for testing a format-checking tool. "
        "All institutions, authors, and findings are imaginary. The English abstract uses "
        "Times New Roman, 12 pt, and 1.5 line spacing as a correct control.",
        east_asia="宋体", ascii_font="Times New Roman", size_pt=12, bold=False,
        line=1.5, indent=2.0,
    )
    add_text_para(
        doc, "Keywords: format checking; fictitious sample; thesis",
        east_asia="宋体", ascii_font="Times New Roman", size_pt=12, bold=False,
        line=1.5, indent=0, space_after_pt=16,
    )

    # E19：手工目录，没有 TOC 域
    add_text_para(
        doc, "目录",
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
        line=1.5, indent=0, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=10,
    )
    for line in [
        "第1章 绪论 ................................ 1",
        "    1.1 研究背景 ............................ 1",
        "    1.3 研究意义 ............................ 2",
        "第二章 方法 ................................ 3",
        "    2.1 实验设计 ............................ 3",
        "第4章 结论 ................................ 4",
        "参考文献 .................................... 4",
    ]:
        add_text_para(
            doc, line,
            east_asia="宋体", ascii_font="Times New Roman", size_pt=12, bold=False,
            line=1.5, indent=0, space_after_pt=2,
        )

    # ---------- 第 2 节：正文 ----------
    # 分节符（新页）
    new_sec = doc.add_section(WD_SECTION.NEW_PAGE)
    # E01 左边距 2.54；E02 上边距 2.00；其余正确
    set_section_page(new_sec, top=2.00, bottom=2.54, left=2.54, right=3.17)
    # E17：不设 start=1；也不设 fmt，避免额外的格式误报
    # 清掉从上一节拷过来的 pgNumType
    sectPr = new_sec._sectPr
    for old in sectPr.findall(qn("w:pgNumType")):
        sectPr.remove(old)
    # E16：正文不写 PAGE 域；E18：页眉写成错误文字
    new_sec.header.is_linked_to_previous = False
    new_sec.footer.is_linked_to_previous = False
    # 清空可能拷贝来的段落
    hdr = new_sec.header
    for p in hdr.paragraphs:
        p.clear()
    hp2 = hdr.paragraphs[0]
    hp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr2 = hp2.add_run("错误的页眉文字")  # E18
    set_run_font(hr2, "宋体", "Times New Roman", 10.5, bold=False)
    ftr = new_sec.footer
    for p in ftr.paragraphs:
        p.clear()
    # 页脚留空，无 PAGE 域（E16）

    # E06 宋体、E07 14 磅（同一标题两处错）
    add_heading_para(
        doc, "第1章 绪论", 1,
        east_asia="宋体", ascii_font="Times New Roman", size_pt=14, bold=True,
    )
    add_text_para(
        doc,
        "本章介绍虚构的研究背景。本段按规范使用宋体、12 磅、1.5 倍行距和首行缩进 2 字符，作为正确对照。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )
    # E04 楷体（字号、行距、缩进正确）
    add_text_para(
        doc,
        "【E04】本段故意将中文字体设为楷体，以对照规范中的宋体要求。其余字号、行距和缩进保持正确。",
        east_asia="楷体", ascii_font="Times New Roman", size_pt=12, line=1.5, indent=2.0,
    )
    # E05 14 磅
    add_text_para(
        doc,
        "【E05】本段故意将字号设为 14 磅，以对照规范中的 12 磅要求。中文字体仍为宋体，行距和缩进保持正确。",
        east_asia="宋体", size_pt=14, line=1.5, indent=2.0,
    )
    # E09 单倍行距
    add_text_para(
        doc,
        "【E09】本段故意使用单倍行距，以对照规范中的 1.5 倍行距要求。中文字体和字号保持正确，并保留首行缩进。",
        east_asia="宋体", size_pt=12, line=1.0, indent=2.0,
    )
    # E10 无首行缩进
    add_text_para(
        doc,
        "【E10】本段故意取消首行缩进，以对照规范中 2 字符缩进的要求。字体、字号和行距保持正确。",
        east_asia="宋体", size_pt=12, line=1.5, indent=0.0,
    )
    # 再一段正确正文
    add_text_para(
        doc,
        "上述对照段落实完毕后，本文继续用规范格式叙述虚构的研究问题。本段同样是正确对照，不埋错误。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )

    # E08：1.1 未加粗（字体字号正确）
    add_heading_para(
        doc, "1.1 研究背景", 2,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=14, bold=False,
    )
    add_text_para(
        doc,
        "研究背景的具体内容为虚构。本段是紧跟二级标题的正确正文对照。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )
    # E12：跳过 1.2，直接 1.3（加粗和字体正确）
    add_heading_para(
        doc, "1.3 研究意义", 2,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=14, bold=True,
    )
    add_text_para(
        doc,
        "研究意义的具体内容为虚构。编号错误是标题本身的问题，本段正文格式正确。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )

    # 图 1、图 2 正确；图 4 跳号（E13）；图 5 字号 12 磅（E15）
    add_placeholder_figure(doc, "图 1  虚构的示意图甲（正确题注对照）", cap_size=10.5)
    add_placeholder_figure(doc, "图 2  虚构的示意图乙（正确题注对照）", cap_size=10.5)
    add_placeholder_figure(doc, "图 4  虚构的示意图，题号故意从 2 跳到 4【E13】", cap_size=10.5)
    add_placeholder_figure(doc, "图 5  虚构的示意图，题注故意使用 12 磅字号【E15】", cap_size=12.0)

    # 第二章 方法：正确的章标题
    add_heading_para(
        doc, "第二章 方法", 1,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
    )
    add_text_para(
        doc,
        "本章说明虚构的方法。章标题使用黑体 16 磅加粗，作为正确对照。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )
    add_heading_para(
        doc, "2.1 实验设计", 2,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=14, bold=True,
    )
    add_text_para(
        doc,
        "实验设计的内容为虚构。本二级标题编号、字体、字号和加粗均正确。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )
    # 正确的三级标题，降低误报风险
    add_heading_para(
        doc, "2.1.1 数据约定", 3,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=12, bold=True,
    )
    add_text_para(
        doc,
        "本小节约定样例中的数据均为虚构数字，不来自真实实验。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )

    # E14：表一
    cap_t = add_text_para(
        doc, "表一  虚构的实验结果（编号故意不用阿拉伯数字）【E14】",
        east_asia="宋体", size_pt=10.5, line=1.5, indent=0,
        align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=4, space_before_pt=10,
    )
    tbl = doc.add_table(rows=3, cols=3)
    tbl.style = "Table Grid"
    headers = ["项目", "数值甲", "数值乙"]
    data = [["对照", "1.0", "2.0"], ["试验", "1.2", "2.1"]]
    for j, h in enumerate(headers):
        cell = tbl.rows[0].cells[j]
        cell.text = ""
        rp = cell.paragraphs[0]
        rp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = rp.add_run(h)
        set_run_font(rr, "黑体", "Times New Roman", 10.5, bold=True)
    for r, row in enumerate(data, start=1):
        for j, val in enumerate(row):
            cell = tbl.rows[r].cells[j]
            cell.text = ""
            rp = cell.paragraphs[0]
            rp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            rr = rp.add_run(val)
            set_run_font(rr, "宋体", "Times New Roman", 10.5, bold=False)

    # E11：第4章（缺第三章）
    add_heading_para(
        doc, "第4章 结论", 1,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
    )
    add_text_para(
        doc,
        "结论内容为虚构。本章标题字体、字号和加粗均正确，错误只在章号跳号。",
        east_asia="宋体", size_pt=12, line=1.5, indent=2.0,
    )

    # 参考文献
    add_heading_para(
        doc, "参考文献", 1,
        east_asia="黑体", ascii_font="Times New Roman", size_pt=16, bold=True,
    )
    # 注意：「参考文献」会被 CHAPTER_RE 匹配吗？「参考文献」不是「第X章」，但 heading level 是 1。
    # classify_regions: text.startswith("参考文献") 在 heading_level 之前？ 
    # 看代码：先看摘要、目录，再看 lvl==1 or CHAPTER，再看参考文献。
    # 「参考文献」的 heading_level 是 1，会先被标成 body，然后才检查 startswith 参考文献！
    # 这是一个 BUG！我需要修 classify_regions，让「参考文献」优先于章标题判断。
    add_text_para(
        doc,
        "[1] 张三. 一项完全虚构的研究[J]. 示例学报, 2020, 12(3): 45-50.",
        east_asia="宋体", size_pt=10.5, line=1.5, indent=0, space_after_pt=4,
    )
    add_text_para(
        doc,
        "[2] 李四. 另一项完全虚构的研究[J]. 示例学报, 8(1): 10-15.【E20】",
        east_asia="宋体", size_pt=10.5, line=1.5, indent=0, space_after_pt=4,
    )
    add_text_para(
        doc,
        "[3] 王五. 第三项完全虚构的研究[M]. 示例出版社, 2021.",
        east_asia="宋体", size_pt=10.5, line=1.5, indent=0, space_after_pt=4,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docx_path = out / "sample_thesis.docx"
    gold_json = out / "gold_errors.json"
    gold_md = out / "sample_errors.md"
    build_docx(docx_path)
    write_gold(gold_json, gold_md)
    print(f"wrote {docx_path}")
    print(f"wrote {gold_json}")
    print(f"wrote {gold_md}")
    print(f"planted {len(GOLD_ERRORS)} errors")


if __name__ == "__main__":
    main()

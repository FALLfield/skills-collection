# -*- coding: utf-8 -*-
"""把预处理后的 tex 交给 pandoc，检查 docx，写转换清单。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

from .util import log, sha256_file, which


def find_bib(project_dir: Path, tex: str, explicit: Optional[str] = None):
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = project_dir / p
        return [p] if p.exists() else []
    paths = []
    for m in re.finditer(r"\\(?:bibliography|addbibresource)\{([^}]+)\}", tex):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part.endswith(".bib"):
                part = part + ".bib"
            cand = project_dir / part
            if cand.exists():
                paths.append(cand)
            else:
                found = list(project_dir.rglob(Path(part).name))
                paths.extend(found[:1])
    if not paths:
        seen = set()
        for p in list(project_dir.glob("*.bib")) + list(project_dir.rglob("*.bib")):
            k = str(p.resolve())
            if k not in seen:
                seen.add(k)
                paths.append(p)
    return paths


def default_csl() -> Optional[Path]:
    # 源码在 ltw/ 下，styles 在包根
    here = Path(__file__).resolve().parent.parent
    p = here / "styles" / "ieee.csl"
    return p if p.exists() else None


def run_pandoc(tex_file: Path, output: Path, bibs, csl, resource_paths) -> tuple:
    pandoc = which("pandoc")
    if not pandoc:
        raise RuntimeError(
            "找不到 pandoc。请安装 pandoc 3.x 并保证在 PATH 中"
            "（https://pandoc.org/installing.html）。"
        )
    cmd = [
        pandoc, str(tex_file),
        "-f", "latex",
        "-t", "docx",
        "-o", str(output),
        "--resource-path=" + os.pathsep.join(str(p) for p in resource_paths),
        "--standalone",
    ]
    if bibs:
        cmd.append("--citeproc")
        for b in bibs:
            cmd.append("--bibliography=" + str(b))
        if csl and Path(csl).exists():
            cmd.append("--csl=" + str(csl))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    stderr = (proc.stderr or "") + (proc.stdout or "")
    return proc.returncode, stderr


def inspect_docx(docx: Path) -> dict:
    info = {
        "omath": 0,
        "omath_para": 0,
        "tables": 0,
        "drawings": 0,
        "raw_tex_hits": [],
        "exposed_labels": [],
        "bibliography_items": 0,
        "text_len": 0,
        "unresolved_qq": 0,
        "text": "",
    }
    if not docx.exists():
        return info
    from lxml import etree
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml")
    root = etree.fromstring(xml)
    info["omath"] = len(root.xpath('//*[local-name()="oMath"]'))
    info["omath_para"] = len(root.xpath('//*[local-name()="oMathPara"]'))
    info["tables"] = len(root.xpath('//*[local-name()="tbl"]'))
    info["drawings"] = len(root.xpath('//*[local-name()="drawing"]'))
    texts = root.xpath('//*[local-name()="t"]')
    alltext = "".join(t.text or "" for t in texts)
    info["text_len"] = len(alltext)
    info["text"] = alltext
    for pat, name in [
        (r"\\begin\{[a-zA-Z*]+\}", "begin"),
        (r"\\leftidx", "leftidx"),
        (r"\\includegraphics", "includegraphics"),
        (r"\[(?:eq|fig|tab|tbl|sec|alg|table|figure)[:.][^\]]+\]", "exposed_label"),
    ]:
        ms = re.findall(pat, alltext)
        if ms:
            info["raw_tex_hits"].append({
                "pattern": name, "count": len(ms), "examples": ms[:8],
            })
    info["exposed_labels"] = re.findall(
        r"\[(?:eq|fig|tab|tbl|sec|alg|table|figure|eqn)[:.][^\]]+\]", alltext
    )
    info["unresolved_qq"] = len(re.findall(r"\?\?", alltext))
    info["bibliography_items"] = count_bibliography(alltext)
    # 表没进 Word 时常见「Mass & 0.583」一类残片；排除期刊名里的 "Intelligent & Robotic"
    raw_amp = re.findall(r".{0,24}\s&\s.{0,24}", alltext)
    amp = []
    for a in raw_amp:
        if re.search(r"\d\s*&", a) or a.count("&") >= 2 or "\\" in a:
            amp.append(a.strip())
    info["ampersand_leftovers"] = amp[:12]
    info["ampersand_count"] = len(amp)
    return info


def write_report(path: Path, meta: dict) -> None:
    lines = [
        "# 转换清单",
        "",
        "- 工具：latex_to_word.py",
        "- 输入：%s" % meta.get("input"),
        "- 输出：%s" % meta.get("output"),
        "- 编号风格：%s" % meta.get("style"),
        "",
        "## 成功",
    ]
    for s in meta.get("success") or ["（见下方计数）"]:
        lines.append("- %s" % s)
    lines += ["", "## 降级成图片"]
    deg = meta.get("degraded") or []
    if deg:
        for s in deg:
            lines.append("- %s" % s)
    else:
        lines.append("- 无（本篇没有把公式整页截图；若有 PDF 图则已转成 PNG 嵌入）")
    lines += ["", "## 需手改"]
    need = meta.get("need_hand") or []
    if need:
        for s in need:
            lines.append("- %s" % s)
    else:
        lines.append("- 本轮扫描未发现必须手改的残留（仍不担保排版符合期刊）")
    lines += ["", "## 计数（本工具内部，不等于验收结论）"]
    for k, v in (meta.get("counts") or {}).items():
        lines.append("- %s：%s" % (k, v))
    lines += ["", "## pandoc 警告（摘录）"]
    warn = (meta.get("pandoc_stderr") or "").strip()
    if warn:
        clip = warn if len(warn) < 8000 else warn[:8000] + "\n…（已截断）"
        lines += ["```", clip, "```"]
    else:
        lines.append("- 无")
    lines += [
        "",
        "## 说明",
        "- 只担保内容结构尽量不丢，不担保排版符合某期刊。",
        "- 自定义宏包、TikZ 等若无法展开，会列入「需手改」或「降级」。",
        "- 交叉引用已解析为静态编号（与转换时的编号一致），不是 Word 域的自动更新字段。",
        "- 参考文献由 `.bib` 经 pandoc citeproc 生成；默认 IEEE 编号体例，与原文 bst 可能不同。",
        "- 「文献被静默丢弃」检查只比较「源码引用且 bib 中存在的键数」与 docx 文献表条数；文献已进入文末文献表、但正文或题注里的引用处没有显示编号时，该比对不会响。源码 wraptable/wrapfigure 题注若未进入 Word，会另行列入需手改。",
        "- 运行时全部本机，不访问网络、不用 GPU、不登录账号。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")



def count_bibliography(alltext: str) -> int:
    """从正文末尾的编号条目 [1]..[N] 计参考文献条数。

    只接受从 1 起连续出现的编号，忽略年份（如 [1990]）这类离群括号数字。
    """
    lower = alltext.lower()
    tail = alltext
    found_heading = False
    for heading in ("references", "bibliography", "works cited", "参考文献"):
        idx = lower.rfind(heading)
        if idx >= 0 and idx > len(alltext) * 0.2:
            tail = alltext[idx:]
            found_heading = True
            break
    if not found_heading:
        tail = alltext[int(len(alltext) * 0.55):]
    nums = set(int(x) for x in re.findall(r"\[(\d+)\]", tail))
    n = 0
    while (n + 1) in nums and n + 1 <= 500:
        n += 1
    return n




def content_sha256(docx: Path) -> str:
    """内容级校验：按条目名排序后对每个 zip 成员做 sha256，再总哈希。

    不受 zip 本地时间戳影响；若 core.xml 的创建时间已在后处理里固定，重复转换应得同一值。
    """
    import hashlib
    hlist = []
    with zipfile.ZipFile(docx) as z:
        for name in sorted(z.namelist()):
            digest = hashlib.sha256(z.read(name)).hexdigest()
            hlist.append("%s  %s" % (digest, name))
    return hashlib.sha256("\n".join(hlist).encode("utf-8")).hexdigest()


def _freeze_core_xml(data: bytes) -> bytes:
    """把核心属性里的创建/修改时间固定，减少「同一输入两次转换哈希不同」。"""
    try:
        text = data.decode("utf-8")
    except Exception:
        return data
    text = re.sub(
        r"<dcterms:created[^>]*>[^<]*</dcterms:created>",
        "<dcterms:created xsi:type=\"dcterms:W3CDTF\">2020-01-01T00:00:00Z</dcterms:created>",
        text,
    )
    text = re.sub(
        r"<dcterms:modified[^>]*>[^<]*</dcterms:modified>",
        "<dcterms:modified xsi:type=\"dcterms:W3CDTF\">2020-01-01T00:00:00Z</dcterms:modified>",
        text,
    )
    return text.encode("utf-8")


def _sanitize_abs_paths(name: str, data: bytes) -> bytes:
    """去掉 custom.xml 里 pandoc 写入的 CSL 绝对路径，改成文件名（ieee.csl）。

    只处理 docProps/custom.xml 的属性值，避免误伤正文里的 DOI / URL。
    这样整文件 sha256 在不同目录下也能复现，且不泄漏内部路径。
    """
    if name != "docProps/custom.xml":
        return data
    try:
        text = data.decode("utf-8")
    except Exception:
        return data

    def csl_repl(m):
        fname = m.group(2).rstrip("/").split("/")[-1]
        if "\\" in fname:
            fname = fname.replace("\\", "/").split("/")[-1]
        return m.group(1) + fname + m.group(3)

    text = re.sub(
        r'(<property\b[^>]*\bname="csl"[^>]*>\s*<vt:lpwstr>)([^<]*)(</vt:lpwstr>)',
        csl_repl,
        text,
        flags=re.I,
    )

    def path_repl(m):
        fname = m.group(2).rstrip("/").split("/")[-1]
        return m.group(1) + fname + m.group(3)

    text = re.sub(
        r'(<vt:lpwstr>)(?:file://)?/(?:workspace|tmp|home|Users)[^<]*/([^/<\s]+)(</vt:lpwstr>)',
        path_repl,
        text,
    )
    return text.encode("utf-8")


def _zip_write_normalized(path: Path, members: dict, document_xml: bytes) -> None:
    """重写 docx，条目时间固定为 2020-01-01，压缩方式确定。"""
    import hashlib
    tmp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        # 保持 document.xml 在前，其余按原名顺序，时间戳固定
        order = ["word/document.xml"] + [n for n in members if n != "word/document.xml"]
        seen = set()
        for name in order:
            if name in seen:
                continue
            seen.add(name)
            data = document_xml if name == "word/document.xml" else members[name]
            if name == "docProps/core.xml":
                data = _freeze_core_xml(data)
            data = _sanitize_abs_paths(name, data)
            info = zipfile.ZipInfo(filename=name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    tmp.replace(path)


def postprocess_docx(docx: Path, n_equations: int = 0, add_eq_numbers: bool = True,
                     demote_unnumbered: bool = True) -> dict:
    """默认给编号展示公式补 (1)(2)…；把无编号展示公式从 oMathPara 降为行内 oMath（仍可编辑）。

    编号公式靠预处理写入的 EQNMARK{n}END 识别。无标记的展示公式视为无编号。
    同时固定 core.xml 时间戳与 zip 条目时间，便于内容级哈希稳定。
    """
    from lxml import etree
    from .texfix import EQ_MARK_RE, EQ_MARK_PREFIX

    notes = []
    if not docx.exists():
        return {"notes": ["docx 不存在，未做后处理"], "eq_numbers_added": 0, "bib_n": 0,
                "demoted": 0, "content_sha256": ""}
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml")
        namelist = z.namelist()
        others = {n: z.read(n) for n in namelist if n != "word/document.xml"}
    root = etree.fromstring(xml)

    def para_text(p):
        return "".join(t.text or "" for t in p.xpath('.//*[local-name()="t"]'))

    def strip_markers(p):
        """去掉 EQNMARK{n}END，返回找到的编号列表。"""
        found = []
        for tnode in p.xpath('.//*[local-name()="t"]'):
            if not tnode.text:
                continue
            def keep(m):
                found.append(int(m.group(1)))
                return ""
            tnode.text = EQ_MARK_RE.sub(keep, tnode.text)
            # 清理因此留下的多余空格
            if tnode.text is not None:
                tnode.text = re.sub(r"[ \t]+", " ", tnode.text)
        return found

    def demote_para(p):
        """把段落里的 oMathPara 换成其中的 oMath（行内，仍是可编辑 OMML）。"""
        n = 0
        for omp in list(p.xpath('.//*[local-name()="oMathPara"]')):
            parent = omp.getparent()
            if parent is None:
                continue
            idx = list(parent).index(omp)
            maths = [c for c in list(omp) if c.tag.split("}")[-1] == "oMath"]
            for j, mnode in enumerate(maths):
                omp.remove(mnode)
                parent.insert(idx + j, mnode)
            parent.remove(omp)
            n += 1
        return n

    def already_numbered(text: str) -> bool:
        return bool(re.search(r"\(\d+[a-z]?\)\s*$", (text or "").strip()))

    def append_number(p, n):
        r = etree.SubElement(p, W + "r")
        tnode = etree.SubElement(r, W + "t")
        tnode.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        tnode.text = "    (%d)" % n

    numbered_added = 0
    demoted = 0
    marked_nums = []
    # 注意：不能用 id() 跨两次 xpath 认段落——lxml 每次可能返回新代理对象。
    # 在同一次遍历里收集「保留 / 降级」列表。
    to_keep = []
    to_demote = []
    all_display = []
    for p in root.xpath('//*[local-name()="p"]'):
        marks = strip_markers(p)
        has_display = bool(p.xpath('.//*[local-name()="oMathPara"]'))
        if has_display:
            all_display.append(p)
        if marks:
            marked_nums.extend(marks)
        if has_display and marks:
            to_keep.append((p, marks))
            if add_eq_numbers and not already_numbered(para_text(p)):
                append_number(p, marks[0])
                numbered_added += 1
        elif has_display and not marks:
            to_demote.append(p)

    # 降级策略：
    # - 若找到了 EQNMARK：只保留带标记的展示公式，其余降为行内 OMML
    # - 若源码编号公式数为 0：全部降为行内（本篇没有编号展示公式）
    # - 若源码有编号公式但标记全丢失：不降级，按出现顺序补号（回退）
    if demote_unnumbered and (to_keep or n_equations == 0):
        targets = to_demote if to_keep else all_display
        for p in targets:
            demoted += demote_para(p)
    elif add_eq_numbers and not marked_nums:
        leftover = [p for p in root.xpath('//*[local-name()="p"]')
                    if p.xpath('.//*[local-name()="oMathPara"]')]
        n = 0
        for p in leftover:
            if already_numbered(para_text(p)):
                continue
            n += 1
            append_number(p, n)
        if n:
            numbered_added = n
            notes.append("给 %d 个展示公式补了编号 (1)…(%d)（无标记回退）" % (n, n))

    if numbered_added and marked_nums:
        notes.append("给 %d 个展示公式补了编号（按源码编号公式标记）" % numbered_added)

    if demoted:
        notes.append("把 %d 个无编号展示公式改为行内 OMML（仍可编辑，不计入编号展示公式）" % demoted)

    alltext = "".join(t.text or "" for t in root.xpath('.//*[local-name()="t"]'))
    has_heading = any(h in alltext.lower() for h in ("references", "bibliography", "参考文献"))
    bib_n = count_bibliography(alltext)
    if bib_n and not has_heading:
        notes.append("docx 参考文献约 %d 条，但未找到 'References' 标题（条目本身已生成）" % bib_n)

    # 去掉临时工作目录路径（否则两次转换因 /tmp/ltw-xxxxx 不同而哈希不同）
    for attr in root.xpath('//@*[contains(., "/tmp/ltw-") or contains(., "\\tmp\\ltw-")]'):
        # attr is a string value, can't set via this xpath easily
        pass
    for el in root.iter():
        for k, v in list(el.attrib.items()):
            if v and ("/tmp/ltw-" in v or "/tmp/" in v):
                # 只留文件名
                from pathlib import Path as _P
                # 可能是 "file:///tmp/ltw-xxx/images/foo.png" 或纯路径
                name = v.replace("\\", "/").split("/")[-1]
                el.attrib[k] = name

    new_xml = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    _zip_write_normalized(docx, others, new_xml)
    notes.append("已写回后处理 docx（已固定文档时间戳）")
    csha = content_sha256(docx)
    notes.append("内容级 sha256=%s…" % csha[:16])
    return {
        "notes": notes,
        "eq_numbers_added": numbered_added,
        "bib_n": bib_n,
        "demoted": demoted,
        "content_sha256": csha,
        "marked_count": len(marked_nums),
    }

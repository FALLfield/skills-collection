# -*- coding: utf-8 -*-
"""让 pandoc 更能吃下的 TeX 改写：数学命令、表格环境、bib 键大小写。"""
from __future__ import annotations

import re
from pathlib import Path

from .util import find_env_end, parse_braced, parse_bracketed, parse_command_name

FONT_SIZE_SWITCHES = {
    "tiny", "scriptsize", "footnotesize", "small", "normalsize",
    "large", "Large", "LARGE", "huge", "Huge",
}

MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*",
    "displaymath", "subequations", "math", "array",
}


def sanitize_math(tex: str) -> str:
    """去掉数学里 pandoc 不认的字号开关、把 \\textsc 改成 \\text、把 \\coloneqq 等改成等价写法。"""
    tex = _rewrite_in_math(tex, _fix_math_chunk)
    # 全局兜底：文中若有未配对的 $，上面的行走可能提前结束，漏掉后半篇。
    # _fix_math_chunk 只改已知命令，对全文调用是安全的。
    tex = _fix_math_chunk(tex)
    return tex


def _fix_math_chunk(s: str) -> str:
    i = 0
    out = []
    n = len(s)
    while i < n:
        if s[i] == "\\":
            name, j = parse_command_name(s, i)
            if name in FONT_SIZE_SWITCHES:
                i = j
                continue
            if name == "textsc":
                arg, k = parse_braced(s, j)
                if arg is not None:
                    out.append("\\text{" + arg + "}")
                    i = k
                    continue
            if name in {"coloneqq", "Coloneqq", "eqqcolon"}:
                out.append(":=")
                i = j
                continue
            if name == "limits":
                # \sum\limits 的 \limits  pandoc 有时可以；保留
                out.append(s[i:j])
                i = j
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _rewrite_in_math(tex: str, fn) -> str:
    """对 $...$、$$...$$、\\[...\\]、数学环境体调用 fn。"""
    i = 0
    out = []
    n = len(tex)
    while i < n:
        # $$ or $
        if tex.startswith("$$", i):
            end = tex.find("$$", i + 2)
            if end < 0:
                out.append(tex[i])
                i += 1
                continue
            out.append("$$")
            out.append(fn(tex[i + 2:end]))
            out.append("$$")
            i = end + 2
            continue
        if tex[i] == "$" and (i == 0 or tex[i - 1] != "\\"):
            end = tex.find("$", i + 1)
            if end < 0:
                out.append(tex[i])
                i += 1
                continue
            out.append("$")
            out.append(fn(tex[i + 1:end]))
            out.append("$")
            i = end + 1
            continue
        if tex.startswith("\\[", i):
            end = tex.find("\\]", i + 2)
            if end < 0:
                out.append(tex[i])
                i += 1
                continue
            out.append("\\[")
            out.append(fn(tex[i + 2:end]))
            out.append("\\]")
            i = end + 2
            continue
        if tex.startswith("\\begin{", i):
            arg, k = parse_braced(tex, i + 6)
            env = (arg or "").strip()
            if env in MATH_ENVS:
                end = find_env_end(tex, k, env)
                end_pat = "\\end{" + env + "}"
                body_end = tex.rfind(end_pat, k, end)
                if body_end < 0:
                    body_end = end
                out.append(tex[i:k])
                out.append(fn(tex[k:body_end]))
                out.append(tex[body_end:end])
                i = end
                continue
        out.append(tex[i])
        i += 1
    return "".join(out)


def simplify_tables(tex: str) -> str:
    """tabularx / tabulary / tabular* 改成 tabular；简化列规，去掉 shortstack 等 pandoc 易摔的命令。"""
    tex = _env_to_tabular(tex, "tabularx", width_first=True)
    tex = _env_to_tabular(tex, "tabulary", width_first=True)
    tex = _env_to_tabular(tex, "tabular*", width_first=True)
    tex = _rewrite_shortstack(tex)
    # 双竖线列规
    tex = re.sub(
        r"\\begin\{tabular\}\{([^}]*)\}",
        lambda m: "\\begin{tabular}{" + m.group(1).replace("||", "|") + "}",
        tex,
    )
    return tex


def _simplify_colspec(spec: str) -> str:
    """把 tabularx 的 X / Y、*{n}{...}、@{...}、>{...} 收成 pandoc 能认的 l/c/r。"""
    s = spec
    # 先展开 *{n}{...}（可嵌套一层）
    def exp_star(m):
        n = int(m.group(1))
        body = m.group(2)
        return body * n
    for _ in range(4):
        ns = re.sub(r"\*\{(\d+)\}\{([^{}]*)\}", exp_star, s)
        if ns == s:
            break
        s = ns
    # 去掉 @{...} >{...} <{...} !{...}
    s = re.sub(r"[@>!<]\{[^{}]*\}", "", s)
    # 自定义列 X Y Z W 当 c
    s = re.sub(r"[XYZW]", "c", s)
    # 去掉多余空格
    s = re.sub(r"\s+", "", s)
    if not s:
        s = "l"
    return s


def _env_to_tabular(tex: str, env: str, width_first: bool = True) -> str:
    i = 0
    out = []
    n = len(tex)
    begin = "\\begin{" + env + "}"
    while True:
        pos = tex.find(begin, i)
        if pos < 0:
            out.append(tex[i:])
            break
        out.append(tex[i:pos])
        k = pos + len(begin)
        _, k = parse_bracketed(tex, k)  # [t] 之类
        if width_first:
            _w, k = parse_braced(tex, k)  # {\textwidth}
            # 有的写 \begin{tabular*}{\linewidth}{@{}l@{}} — width then col
        # 可选 @{} 已在 colspec
        col, k2 = parse_braced(tex, k)
        if col is None:
            # 保底：原样
            end = find_env_end(tex, k, env)
            out.append(tex[pos:end])
            i = end
            continue
        new_col = _simplify_colspec(col)
        end = find_env_end(tex, k2, env)
        end_pat = "\\end{" + env + "}"
        body_end = tex.rfind(end_pat, k2, end)
        if body_end < 0:
            body_end = end
        body = tex[k2:body_end]
        out.append("\\begin{tabular}{" + new_col + "}")
        out.append(body)
        out.append("\\end{tabular}")
        i = end
    return "".join(out)


def _rewrite_shortstack(tex: str) -> str:
    i = 0
    out = []
    n = len(tex)
    while i < n:
        if tex.startswith("\\shortstack", i) and (i + 11 == n or not tex[i + 11].isalpha()):
            k = i + 11
            _, k = parse_bracketed(tex, k)
            arg, k2 = parse_braced(tex, k)
            if arg is not None:
                # \\ 改成空格
                flat = re.sub(r"\\\\", " ", arg)
                flat = re.sub(r"\s+", " ", flat).strip()
                out.append(flat)
                i = k2
                continue
        out.append(tex[i])
        i += 1
    return "".join(out)


def normalize_bib_file(bib_text: str) -> str:
    """规范化 .bib：键改小写；缺 year/date 的条目补 year = {n.d.}。

    citeproc 对无日期的 @misc 等会静默丢掉，既不进参考文献，正文引用也消失。
    「n.d.」是常见的 no-date 写法，不是为某一条特写的补丁。
    """
    def lower_key(m):
        return m.group(1) + m.group(2).lower() + m.group(3)
    bib_text = re.sub(
        r"(@\w+\s*\{\s*)([^,\s]+)(\s*,)",
        lower_key,
        bib_text,
    )
    return _fill_missing_years(bib_text)


def _fill_missing_years(bib_text: str) -> str:
    """给没有 year 或 date 字段的条目补 year = {n.d.}。"""
    parts = re.split(r"(@\w+\s*\{)", bib_text)
    out = [parts[0]]
    i = 1
    while i < len(parts):
        header = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if not re.search(r"(?im)^\s*(year|date)\s*=", body):
            m = re.match(r"([^,]*+,)", body, re.S)
            if m:
                body = m.group(1) + "\n    year = {n.d.}," + body[m.end():]
        out.append(header + body)
        i += 2
    return "".join(out)


def collect_cite_keys(tex: str):
    """收集正文里 \\cite / \\nocite 等用到的键（小写、去重、保序）。"""
    keys = []
    seen = set()
    for m in re.finditer(
        r"\\(?:cite[a-zA-Z]*|nocite)\*?\s*(?:\[[^\]]*\]){0,2}\s*\{([^}]+)\}",
        tex,
    ):
        for k in m.group(1).split(","):
            k = k.strip().lower()
            if k and not re.match(r"^#\d+$", k) and k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def bib_entry_keys(bib_text: str):
    """bib 文件里的条目键（小写）。"""
    return [k.lower() for k in re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib_text)]


def append_nocite(tex: str, keys) -> str:
    """在 \\end{document} 前写入 \\nocite{...}，避免表注里的引用随表一起丢掉。"""
    if not keys:
        return tex
    blob = "\\nocite{" + ",".join(keys) + "}\n"
    m = re.search(r"\\end\{document\}", tex)
    if m:
        return tex[:m.start()] + blob + tex[m.start():]
    return tex + "\n" + blob


def lowercase_cite_keys_in_tex(tex: str) -> str:
    """\\cite{ReZK} 与 bib 小写键对齐。"""
    def repl(m):
        keys = ",".join(k.strip().lower() for k in m.group(2).split(","))
        return m.group(1) + keys + "}"
    return re.sub(
        r"(\\cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]){0,2}\s*\{)([^}]+)\}",
        repl,
        tex,
    )


# 编号公式标记，后处理时用来区分「该计题号的展示公式」和「无编号展示公式」。
EQ_MARK_PREFIX = "EQNMARK"
EQ_MARK_RE = re.compile(r"EQNMARK(\d+)END")


def stamp_numbered_equation_markers(tex: str) -> tuple:
    """在编号展示公式体末尾写入 EQNMARK{n}END（用 \\text），供后处理识别。

    返回 (新 tex, 编号个数)。不给 equation* / \\nonumber 行打标。
    """
    from .refs import NUMBERED_MATH, Numbering, detect_style
    from .util import split_top_level

    style = detect_style(tex)
    num = Numbering(style=style)
    i = 0
    out = []
    pat = re.compile(
        r"\\begin\{(" + "|".join(map(re.escape, sorted(NUMBERED_MATH | {"subequations"}))) + r")\}"
    )

    def stamp(chunk, n):
        if EQ_MARK_PREFIX in chunk:
            return chunk
        return chunk.rstrip() + " \\text{" + EQ_MARK_PREFIX + n + "END}\n"

    while True:
        m = pat.search(tex, i)
        if not m:
            out.append(tex[i:])
            break
        env = m.group(1)
        out.append(tex[i:m.start()])
        after = m.end()
        end = find_env_end(tex, after, env)
        inner_end = tex.rfind("\\end{" + env + "}", after, end)
        body = tex[after:inner_end if inner_end >= 0 else end]

        if env == "equation":
            if re.search(r"\\nonumber|\\notag", body) and not re.search(r"\\tag\s*\{", body):
                new_body = body
            else:
                num.equation += 1
                new_body = stamp(body, num.the_equation())
        elif env == "subequations":
            num.equation += 1
            new_body = body  # 子编号较复杂，整块不加标记（计数在 collect 已处理）
        else:
            rows = split_top_level(body, "\\\\")
            new_rows = []
            for row in rows:
                if (not row.strip()) or (
                    re.search(r"\\nonumber|\\notag", row) and not re.search(r"\\tag\s*\{", row)
                ):
                    new_rows.append(row)
                    continue
                num.equation += 1
                new_rows.append(stamp(row, num.the_equation()))
            new_body = "\\\\\n".join(new_rows)
        out.append(tex[m.start():after])
        out.append(new_body)
        out.append(tex[inner_end if inner_end >= 0 else end:end])
        i = end
    return "".join(out), num.equation

def _brace_group(tex: str, open_idx: int):
    """open_idx 指向 '{'，返回 (内容, 闭合后下标)。"""
    depth = 1
    j = open_idx + 1
    while j < len(tex) and depth:
        c = tex[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        j += 1
    return tex[open_idx + 1:j - 1], j


def _caption_plain(cap: str) -> str:
    """题注去命令，得到可在 docx 里查找的近似纯文本。"""
    t = cap
    t = re.sub(r"\\cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]){0,2}\s*\{[^}]*\}", "", t)
    t = re.sub(
        r"\\(?:ref|eqref|autoref|cref|Cref|label|texttt|emph|textbf|textit|text|sysname|xspace)\*?\s*\{([^}]*)\}",
        r"\1",
        t,
    )
    t = re.sub(r"\\sysname\b", "FlashMoE", t)
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = re.sub(r"[{}$~\\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([.,;:])", r"\1", t)
    return t


def collect_wrap_float_captions(tex: str):
    """收集 wraptable / wrapfigure（含带星号）里的题注。"""
    from .util import find_env_end
    pat = re.compile(r"\\begin\{(wraptable\*?|wrapfigure\*?)\}")
    items = []
    i = 0
    while True:
        m = pat.search(tex, i)
        if not m:
            break
        env = m.group(1)
        end = find_env_end(tex, m.end(), env)
        body = tex[m.end():end]
        # 丢掉 \end{env} 之前已由 find_env_end 处理？看它返回的是 end 标签前还是后
        # 用 body 到 \end
        end_tag = body.rfind("\\end{" + env + "}")
        if end_tag >= 0:
            body = body[:end_tag]
        labels = re.findall(r"\\label\{([^}]+)\}", body)
        caps = []
        for cm in re.finditer(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body):
            cap, _ = _brace_group(body, cm.end() - 1)
            cites = []
            seen = set()
            for km in re.finditer(
                r"\\cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]){0,2}\s*\{([^}]+)\}", cap
            ):
                for k in km.group(1).split(","):
                    k = k.strip()
                    if k and k not in seen:
                        seen.add(k)
                        cites.append(k)
            caps.append({"raw": cap, "plain": _caption_plain(cap), "cites": cites})
        items.append({"env": env, "labels": labels, "captions": caps, "pos": m.start()})
        i = m.end() if end <= m.end() else end
    return items


def _docx_norm(text: str) -> str:
    t = text.replace("\xa0", " ").replace("\u200b", " ")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _caption_present(plain: str, docx_norm: str) -> bool:
    """题注是否出现在 docx 正文里（用连续词组，避免单词语在别处误命中）。"""
    if not plain or not plain.strip():
        return True
    words = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{3,}", plain)
    blob = " ".join(w.lower() for w in words)
    if not words:
        return True
    if len(words) <= 3:
        return blob in docx_norm or " ".join(words).lower() in docx_norm
    grams = [" ".join(words[k:k + 4]).lower() for k in range(len(words) - 3)]
    hits = sum(1 for g in grams if g in docx_norm)
    if len(grams) <= 2:
        return hits >= 1
    return hits >= 2


def missing_wrap_captions(tex: str, docx_text: str):
    """源码 wraptable/wrapfigure 题注在 docx 中缺失时，返回需手改文句列表。"""
    docx_norm = _docx_norm(docx_text or "")
    notes = []
    for item in collect_wrap_float_captions(tex):
        lab = item["labels"][0] if item["labels"] else ""
        lab_s = "（%s）" % lab if lab else ""
        for cap in item["captions"]:
            plain = cap["plain"]
            if _caption_present(plain, docx_norm):
                continue
            quote = plain
            # 优先取第一句，便于对照源码
            sent = re.split(r"(?<=[.。])\s+", quote, maxsplit=1)[0].strip()
            if 20 <= len(sent) <= 160:
                quote = sent
            elif len(quote) > 140:
                cut = quote[:140]
                sp = cut.rfind(" ")
                quote = (cut[:sp] if sp > 80 else cut).rstrip(" ,;:") + "…"
            line = "源码 %s%s题注正文未进入 Word：「%s」" % (item["env"], lab_s, quote)
            if cap["cites"]:
                keys = ", ".join("\\cite{%s}" % k for k in cap["cites"])
                line += (
                    "；题注中的 %s 在正文中未显示为文献编号（该条只出现在文末文献表，"
                    "「文献被静默丢弃」条数比对不会发现这种情况）"
                    % keys
                )
            line += "，需手改"
            notes.append(line)
    return notes

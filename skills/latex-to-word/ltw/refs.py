# -*- coding: utf-8 -*-
"""按文档类风格编号，收集 \\label，并把 \\ref/\\eqref/\\cref 换成编号。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .util import (
    find_env_end, labels_in, log, parse_braced, parse_bracketed,
    parse_command_name, skip_ws, split_top_level, to_roman,
)

NUMBERED_MATH = {"equation", "align", "gather", "multline", "eqnarray", "flalign"}
UNNUMBERED_MATH = {
    "equation*", "align*", "gather*", "multline*", "eqnarray*", "flalign*", "displaymath",
}
FIGURE_ENVS = {"figure", "figure*", "wrapfigure"}
TABLE_ENVS = {"table", "table*", "wraptable"}
ALG_ENVS = {"algorithm", "algorithm2e"}
THEOREM_ENVS = {
    "theorem", "lemma", "definition", "proposition", "corollary",
    "remark", "claim", "example", "conjecture", "assumption",
    "theorem*", "lemma*", "definition*", "proposition*", "corollary*",
}


@dataclass
class LabelInfo:
    key: str
    kind: str
    number: str
    autoref: str


@dataclass
class Numbering:
    style: str = "article"
    section: int = 0
    subsection: int = 0
    subsubsection: int = 0
    equation: int = 0
    figure: int = 0
    table: int = 0
    algorithm: int = 0
    theorem: int = 0
    appendix: bool = False
    current_figure_no: str = ""

    def the_section(self) -> str:
        if self.appendix:
            return chr(64 + self.section) if self.section > 0 else "A"
        if self.style == "ieee":
            return to_roman(self.section)
        return str(self.section)

    def the_subsection(self) -> str:
        sec = self.the_section()
        if self.style == "ieee":
            return "%s-%s" % (sec, chr(64 + self.subsection))
        return "%s.%s" % (sec, self.subsection)

    def the_subsubsection(self) -> str:
        sub = self.the_subsection()
        if self.style == "ieee":
            return "%s%s" % (sub, self.subsubsection)
        return "%s.%s" % (sub, self.subsubsection)

    def the_table(self) -> str:
        if self.style == "ieee":
            return to_roman(self.table)
        return str(self.table)

    def the_figure(self) -> str:
        return str(self.figure)

    def the_equation(self) -> str:
        return str(self.equation)

    def the_algorithm(self) -> str:
        return str(self.algorithm)


def detect_style(tex: str) -> str:
    m = re.search(r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}", tex)
    if not m:
        return "article"
    cls = (m.group(2) or "").lower()
    if "ieee" in cls:
        return "ieee"
    return "article"


def caption_keys_outside_sub(body: str):
    cleaned = re.sub(
        r"\\begin\{subfigure\*?\}.*?\\end\{subfigure\*?\}",
        "",
        body,
        flags=re.S,
    )
    cleaned = re.sub(r"\\subfloat\s*(?:\[[^\]]*\])?\s*\{.*?\}", "", cleaned, flags=re.S)
    caps = list(re.finditer(r"\\caption\s*(?:\[[^\]]*\])?\s*", cleaned))
    if not caps:
        return [], False
    keys = []
    for m in caps:
        arg, end = parse_braced(cleaned, m.end())
        if arg:
            keys.extend(labels_in(arg))
        nearby = cleaned[end:end + 200] if end else ""
        nm = re.match(r"\s*\\label\s*\{([^{}]+)\}", nearby)
        if nm:
            keys.append(nm.group(1))
    return keys, True


def iter_subfigures(body: str):
    i = 0
    letter_i = 0
    while True:
        m = re.search(r"\\begin\{subfigure\*?\}", body[i:])
        m2 = re.search(r"\\subfloat\b", body[i:])
        starts = []
        if m:
            starts.append((i + m.start(), "sub"))
        if m2:
            starts.append((i + m2.start(), "subfloat"))
        if not starts:
            break
        starts.sort()
        pos, kind = starts[0]
        if kind == "sub":
            after = body.find("}", pos) + 1
            _, after = parse_bracketed(body, after)
            _, after = parse_braced(body, after)
            end = find_env_end(body, after, "subfigure")
            inner_end = body.rfind("\\end{subfigure}", after, end)
            inner = body[after:inner_end if inner_end >= 0 else end]
            letter_i += 1
            letter = chr(96 + letter_i)
            keys, _ = caption_keys_outside_sub(inner)
            keys = keys or labels_in(inner)
            for kkey in keys:
                yield kkey, letter
            i = end
        else:
            after = pos + len("\\subfloat")
            cap, after = parse_bracketed(body, after)
            content, after = parse_braced(body, after)
            letter_i += 1
            letter = chr(96 + letter_i)
            blob = (cap or "") + (content or "")
            for kkey in labels_in(blob):
                yield kkey, letter
            i = after


def _register_math_env(env, body, num: Numbering, register):
    if env == "equation":
        tm = re.search(r"\\tag\s*\{", body)
        if tm:
            tag_text, _ = parse_braced(body, tm.end())
            register(labels_in(body), "equation", tag_text or "?",
                     "Equation (" + (tag_text or "?") + ")")
            return
        if re.search(r"\\nonumber|\\notag", body):
            return
        num.equation += 1
        number = num.the_equation()
        register(labels_in(body), "equation", number, "Equation (" + number + ")")
        return
    rows = split_top_level(body, "\\\\")
    for row in rows:
        if not row.strip():
            continue
        tm = re.search(r"\\tag\s*\{", row)
        if tm:
            tag_text, _ = parse_braced(row, tm.end())
            register(labels_in(row), "equation", tag_text or "?",
                     "Equation (" + (tag_text or "?") + ")")
            continue
        if re.search(r"\\nonumber|\\notag", row):
            continue
        num.equation += 1
        number = num.the_equation()
        register(labels_in(row), "equation", number, "Equation (" + number + ")")


def _register_subequations(body, main, register):
    letter_i = 0
    i = 0
    while True:
        m = re.search(r"\\begin\{(equation\*?|align\*?|gather\*?)\}", body[i:])
        if not m:
            break
        env = m.group(1)
        after = i + m.end()
        end = find_env_end(body, after, env)
        inner_end = body.rfind("\\end{" + env + "}", after, end)
        inner = body[after:inner_end if inner_end >= 0 else end]
        if env.endswith("*"):
            i = end
            continue
        if env == "equation":
            letter_i += 1
            number = main + chr(96 + letter_i)
            register(labels_in(inner), "equation", number, "Equation (" + number + ")")
        else:
            for row in split_top_level(inner, "\\\\"):
                if not row.strip() or (
                    re.search(r"\\nonumber|\\notag", row) and not re.search(r"\\tag\s*\{", row)
                ):
                    continue
                letter_i += 1
                number = main + chr(96 + letter_i)
                register(labels_in(row), "equation", number, "Equation (" + number + ")")
        i = end


def collect_and_resolve(tex: str):
    """收集全部 \\label 编号，再把引用换成编号。

    返回 (替换后 tex, 标签表, 引用清单, 计数器)。
    """
    style = detect_style(tex)
    num = Numbering(style=style)
    labels = {}

    def register(keys, kind, number, autoref):
        for k in keys or []:
            k = k.strip()
            if k:
                labels[k] = LabelInfo(k, kind, number, autoref)

    i = 0
    interesting = re.compile(
        r"\\(appendix|section\*?|subsection\*?|subsubsection\*?|chapter\*?|begin|captionof)\b"
    )
    while True:
        m = interesting.search(tex, i)
        if not m:
            break
        cmd = m.group(1)
        if cmd == "appendix":
            num.appendix = True
            num.section = 0
            num.subsection = 0
            i = m.end()
            continue
        if cmd in {
            "section", "section*", "subsection", "subsection*",
            "subsubsection", "subsubsection*", "chapter", "chapter*",
        }:
            starred = cmd.endswith("*")
            kind = cmd.rstrip("*")
            k = m.end()
            _, k = parse_bracketed(tex, k)
            title, k2 = parse_braced(tex, k)
            nearby = tex[k2:k2 + 200] if k2 else ""
            nearby_labs = []
            nm2 = re.match(r"\s*\\label\s*\{([^{}]+)\}", nearby)
            if nm2:
                nearby_labs.append(nm2.group(1))
            keys = labels_in(title or "") + nearby_labs
            if not starred:
                if kind in {"section", "chapter"}:
                    num.section += 1
                    num.subsection = 0
                    num.subsubsection = 0
                    number = num.the_section()
                    auto = ("Appendix " if num.appendix else "Section ") + number
                    register(keys, "section", number, auto)
                elif kind == "subsection":
                    num.subsection += 1
                    num.subsubsection = 0
                    number = num.the_subsection()
                    register(keys, "subsection", number, "Section " + number)
                else:
                    num.subsubsection += 1
                    number = num.the_subsubsection()
                    register(keys, "subsubsection", number, "Section " + number)
            i = k2 if title is not None else m.end()
            continue
        if cmd == "captionof":
            kind_arg, k = parse_braced(tex, m.end())
            cap, k2 = parse_braced(tex, k)
            keys = labels_in(cap or "")
            nearby = tex[k2:k2 + 200] if k2 else ""
            nm = re.match(r"\s*\\label\s*\{([^{}]+)\}", nearby)
            if nm:
                keys.append(nm.group(1))
            kind = (kind_arg or "figure").strip()
            if kind.startswith("tab"):
                num.table += 1
                number = num.the_table()
                register(keys, "table", number, "Table " + number)
            else:
                num.figure += 1
                number = num.the_figure()
                register(keys, "figure", number, "Fig. " + number)
            i = k2 if cap is not None else m.end()
            continue
        if cmd == "begin":
            env, k = parse_braced(tex, m.end())
            env_name = (env or "").strip()
            handled = (
                FIGURE_ENVS | TABLE_ENVS | ALG_ENVS | NUMBERED_MATH | UNNUMBERED_MATH
                | THEOREM_ENVS | {"subequations"}
            )
            if env_name not in handled:
                i = k
                continue
            end_pos = find_env_end(tex, k, env_name)
            end_pat = "\\end{" + env_name + "}"
            body_end = tex.rfind(end_pat, k, end_pos)
            body = tex[k:body_end if body_end >= 0 else end_pos]
            if env_name in FIGURE_ENVS:
                main_cap_keys, has_main_cap = caption_keys_outside_sub(body)
                if has_main_cap:
                    num.figure += 1
                    num.current_figure_no = num.the_figure()
                    register(main_cap_keys, "figure", num.current_figure_no,
                             "Fig. " + num.current_figure_no)
                fno = num.current_figure_no if has_main_cap else str(num.figure + 1)
                for sk, sletter in iter_subfigures(body):
                    number = "%s%s" % (fno, sletter)
                    register([sk], "subfigure", number, "Fig. " + number)
            elif env_name in TABLE_ENVS:
                main_cap_keys, has_main_cap = caption_keys_outside_sub(body)
                keys = main_cap_keys or (labels_in(body) if not has_main_cap else [])
                if has_main_cap or keys:
                    num.table += 1
                    number = num.the_table()
                    register(keys or main_cap_keys or labels_in(body), "table",
                             number, "Table " + number)
            elif env_name in ALG_ENVS:
                cap_keys, has = caption_keys_outside_sub(body)
                keys = cap_keys or labels_in(body)
                num.algorithm += 1
                number = num.the_algorithm()
                register(keys, "algorithm", number, "Algorithm " + number)
            elif env_name in THEOREM_ENVS:
                if not env_name.endswith("*"):
                    num.theorem += 1
                    number = str(num.theorem)
                    keys = labels_in(body)
                    # theorem 标题里也常有 \label
                    register(keys, "theorem", number, env_name.rstrip("*").capitalize() + " " + number)
            elif env_name in NUMBERED_MATH:
                _register_math_env(env_name, body, num, register)
            elif env_name in UNNUMBERED_MATH:
                # LaTeX：无编号公式里的 \label 挂到当前节（官方 PDF 上 \autoref{eq:plonk} 即为此）。
                keys = labels_in(body)
                if keys:
                    if num.subsubsection > 0:
                        number = num.the_subsubsection()
                    elif num.subsection > 0:
                        number = num.the_subsection()
                    elif num.section > 0:
                        number = num.the_section()
                    else:
                        number = "?"
                    register(keys, "section", number, "Section " + number)
            elif env_name == "subequations":
                num.equation += 1
                main = num.the_equation()
                _register_subequations(body, main, register)
            i = end_pos
            continue
        i = m.end()

    ref_log = []

    def replace_refs(s: str) -> str:
        i = 0
        out = []
        n = len(s)
        while i < n:
            if s[i] != "\\":
                out.append(s[i])
                i += 1
                continue
            name, j = parse_command_name(s, i)
            if name == "ref" and j < n and s[j] == "*":
                j += 1
            if name in {"eqref", "ref", "autoref", "cref", "Cref", "pageref", "subref"}:
                keys, k = parse_braced(s, j)
                if keys is None:
                    out.append(s[i:j])
                    i = j
                    continue
                keylist = [x.strip() for x in keys.split(",") if x.strip()]
                rendered = []
                for key in keylist:
                    if re.match(r"^#\d+$", key):
                        # 宏定义残留，不是真实引用
                        continue
                    info = labels.get(key)
                    if not info:
                        rendered.append("??")
                        ref_log.append({
                            "cmd": name, "key": key, "status": "unresolved", "text": "??",
                        })
                        continue
                    if name == "pageref":
                        rendered.append("??")
                        ref_log.append({
                            "cmd": name, "key": key, "status": "pageref-unsupported", "text": "??",
                        })
                        continue
                    if name == "eqref" or (
                        name in {"cref", "Cref", "autoref"} and info.kind == "equation"
                    ):
                        text = "(" + info.number + ")"
                        if name in {"cref", "Cref", "autoref"}:
                            text = "Equation " + text
                    elif name in {"cref", "Cref", "autoref"}:
                        text = info.autoref
                    elif name == "subref":
                        text = info.number[-1] if info.number else "??"
                    else:
                        text = info.number
                    rendered.append(text)
                    ref_log.append({
                        "cmd": name, "key": key, "status": "ok",
                        "kind": info.kind, "number": info.number, "text": text,
                    })
                out.append(", ".join(rendered))
                i = k
                continue
            out.append(s[i:j])
            i = j
        return "".join(out)

    new = replace_refs(tex)
    return new, labels, ref_log, num


def rewrite_algorithms(tex: str):
    """把 algorithm 环境改成带题注的 verbatim，便于进 Word。"""
    notes = []

    def conv_algo(body: str) -> str:
        cap = ""
        m = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*", body)
        if m:
            cap, _ = parse_braced(body, m.end())
            cap = re.sub(r"\\label\s*\{[^{}]+\}", "", cap or "").strip()
        body2 = re.sub(r"\\caption\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", body)
        body2 = re.sub(r"\\label\s*\{[^{}]+\}", "", body2)
        repls = [
            (r"\\[Ss]tate\s*", ""),
            (r"\\[Rr]equire\s*", "Require: "),
            (r"\\[Ee]nsure\s*", "Ensure: "),
            (r"\\[Rr]eturn\s*", "Return "),
            (r"\\[Ii]f\s*", "If "),
            (r"\\[Ee]lse[Ii]f\s*", "Else If "),
            (r"\\[Ee]lse\b", "Else"),
            (r"\\[Ee]nd[Ii]f\b", "End If"),
            (r"\\[Ff]or\s*", "For "),
            (r"\\[Ee]nd[Ff]or\b", "End For"),
            (r"\\[Ww]hile\s*", "While "),
            (r"\\[Ee]nd[Ww]hile\b", "End While"),
            (r"\\[Cc]omment\s*", "// "),
            (r"\\[Pp]rocedure\s*", "Procedure "),
            (r"\\[Ee]nd[Pp]rocedure\b", "End Procedure"),
            (r"\\begin\{algorithmic\}(?:\[[^\]]*\])?", ""),
            (r"\\end\{algorithmic\}", ""),
            (r"\\KwIn\s*", "Input: "),
            (r"\\KwOut\s*", "Output: "),
            (r"\\KwData\s*", "Data: "),
            (r"\\KwResult\s*", "Result: "),
        ]
        for p, rpl in repls:
            body2 = re.sub(p, rpl, body2)
        body2 = body2.strip()
        title = cap or "(algorithm)"
        notes.append("算法「%s」改写成纯文本（Word 里不是浮动算法环境）" % title[:60])
        return "\n\n\\paragraph{Algorithm. %s}\n\n\\begin{verbatim}\n%s\n\\end{verbatim}\n\n" % (
            title, body2
        )

    i = 0
    out = []
    while True:
        m = re.search(r"\\begin\{(algorithm|algorithm2e)\}", tex[i:])
        if not m:
            out.append(tex[i:])
            break
        env = m.group(1)
        abs_s = i + m.start()
        after = i + m.end()
        _, after = parse_bracketed(tex, after)
        end = find_env_end(tex, after, env)
        inner_end = tex.rfind("\\end{" + env + "}", after, end)
        body = tex[after:inner_end if inner_end >= 0 else end]
        out.append(tex[i:abs_s])
        out.append(conv_algo(body))
        i = end
    return "".join(out), notes


def stub_tikz(tex: str):
    notes = []
    i = 0
    out = []
    while True:
        m = re.search(r"\\begin\{tikzpicture\}", tex[i:])
        if not m:
            out.append(tex[i:])
            break
        abs_s = i + m.start()
        after = i + m.end()
        end = find_env_end(tex, after, "tikzpicture")
        notes.append(
            "TikZ 图无法在本工具内编译，已留占位，需手改或自行导出图片后用 \\includegraphics 替换"
        )
        out.append(tex[i:abs_s])
        out.append("\n\n[TikZ figure omitted — see conversion report]\n\n")
        i = end
    return "".join(out), notes


def tidy_preamble(tex: str) -> str:
    def repl_dclass(m):
        opts = m.group(1) or ""
        cls = m.group(2) or ""
        if cls.lower() in {"article", "report", "book", "minimal"}:
            return m.group(0)
        keep = []
        for o in opts.split(","):
            o = o.strip()
            if o in {"10pt", "11pt", "12pt", "a4paper", "letterpaper"}:
                keep.append(o)
        opt_s = "[" + ",".join(keep) + "]" if keep else ""
        return "\\documentclass" + opt_s + "{article}"

    tex = re.sub(
        r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}",
        repl_dclass,
        tex,
        count=1,
    )
    tex = re.sub(r"\\(this)?pagestyle\{[^}]*\}", "", tex)
    tex = re.sub(r"\\fancy[a-zA-Z]*\{[^}]*\}", "", tex)
    return tex


def append_equation_numbers(tex: str, style: str = "article") -> str:
    """在编号展示公式末尾写入 \\quad (N)，让 pandoc 把编号带进 Word。不给 equation* / nonumber 行编号。"""
    num = Numbering(style=style)
    i = 0
    out = []
    pat = re.compile(r"\\begin\{(" + "|".join(map(re.escape, sorted(NUMBERED_MATH | {"subequations"}))) + r")\}")
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
        tail = tex[inner_end if inner_end >= 0 else end:end]  # the \end{...}

        def stamp(chunk, n):
            # 避免已有 tag
            if re.search(r"\\tag\s*\{", chunk) or re.search(r"\(\d+[a-z]?\)\s*$", chunk.strip()):
                return chunk
            return chunk.rstrip() + " \\quad (" + n + ")\n"

        if env == "equation":
            if re.search(r"\\nonumber|\\notag", body) and not re.search(r"\\tag\s*\{", body):
                new_body = body
            elif re.search(r"\\tag\s*\{", body):
                new_body = body
            else:
                num.equation += 1
                new_body = stamp(body, num.the_equation())
        elif env == "subequations":
            num.equation += 1
            main = num.the_equation()
            # 不改主计数，内部 a,b 由 latex 管；这里简单给整块不加号
            new_body = body
        else:
            rows = split_top_level(body, "\\\\")
            new_rows = []
            for ri, row in enumerate(rows):
                is_last = ri == len(rows) - 1
                if (not row.strip()) or (re.search(r"\\nonumber|\\notag", row) and not re.search(r"\\tag\s*\{", row)) or re.search(r"\\tag\s*\{", row):
                    new_rows.append(row)
                    continue
                num.equation += 1
                new_rows.append(stamp(row, num.the_equation()))
            new_body = "\\\\\n".join(new_rows)
        out.append(tex[m.start():after])
        out.append(new_body)
        out.append(tex[inner_end if inner_end >= 0 else end:end])
        i = end
    return "".join(out)


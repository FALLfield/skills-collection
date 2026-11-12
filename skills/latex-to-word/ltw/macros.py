# -*- coding: utf-8 -*-
"""收集、展开用户宏，并改写 pandoc 不认识的常见命令。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .util import log, parse_braced, parse_bracketed, parse_command_name, skip_ws

DO_NOT_EXPAND = {
    "begin", "end", "input", "include", "documentclass", "usepackage",
    "label", "ref", "eqref", "autoref", "cref", "Cref", "pageref", "subref",
    "cite", "citep", "citet", "citealp", "citeyear", "citeauthor", "citetext",
    "bibliography", "bibliographystyle", "addbibresource", "nocite",
    "caption", "captionof", "includegraphics", "includesvg",
    "section", "subsection", "subsubsection", "chapter", "paragraph",
    "appendix", "maketitle", "tableofcontents", "footnote", "thanks",
    "newcommand", "renewcommand", "providecommand", "def", "let", "edef",
    "gdef", "xdef", "DeclareRobustCommand", "DeclareMathOperator",
    "newenvironment", "renewenvironment", "NewDocumentCommand",
    "href", "url", "path", "verb", "item",
    "frac", "dfrac", "tfrac", "sqrt", "sum", "prod", "int", "lim",
    "max", "min", "inf", "sup",
    "left", "right", "big", "Big", "bigg", "Bigg",
    "mathrm", "mathbf", "mathit", "mathsf", "mathtt", "mathcal", "mathbb",
    "boldsymbol", "textrm", "textbf", "textit", "emph", "text", "mbox",
    "overline", "underline", "hat", "bar", "tilde", "vec", "dot", "ddot",
    "quad", "qquad", "hspace", "vspace",
    "tag", "nonumber", "notag",
    "multicolumn", "multirow", "toprule", "midrule", "bottomrule", "hline",
    "cline", "cmidrule",
    "author", "title", "date", "address", "email",
    "if", "else", "fi", "ifx", "ifdefined",
}


@dataclass
class Macro:
    name: str
    n_args: int
    optional_default: Optional[str]
    body: str


def collect_macros(tex: str):
    macros = []
    i = 0
    n = len(tex)
    while i < n:
        if tex[i] != "\\":
            i += 1
            continue
        name, j = parse_command_name(tex, i)
        if name in {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"}:
            jj = skip_ws(tex, j)
            if jj < n and tex[jj] == "*":
                jj += 1
            arg, k = parse_braced(tex, jj)
            if arg is None:
                nm2, k = parse_command_name(tex, skip_ws(tex, jj))
                macroname = nm2 or ""
            else:
                macroname = arg.lstrip("\\")
            nargs = 0
            opt_def = None
            br, k2 = parse_bracketed(tex, k)
            if br is not None and br.strip().isdigit():
                nargs = int(br.strip())
                k = k2
                br2, k3 = parse_bracketed(tex, k)
                if br2 is not None:
                    opt_def = br2
                    k = k3
            body, k4 = parse_braced(tex, k)
            if body is not None and macroname and macroname not in DO_NOT_EXPAND:
                macros.append(Macro(macroname, nargs, opt_def, body))
            i = k4 if body is not None else j
            continue
        if name == "DeclareMathOperator":
            jj = skip_ws(tex, j)
            starred = jj < n and tex[jj] == "*"
            if starred:
                jj += 1
            cmd, k = parse_braced(tex, jj)
            text, k2 = parse_braced(tex, k)
            if cmd and text is not None:
                cname = cmd.lstrip("\\")
                body = ("\\operatorname*{" + text + "}") if starred else ("\\operatorname{" + text + "}")
                macros.append(Macro(cname, 0, None, body))
            i = k2 if text is not None else j
            continue
        i = j if j > i else i + 1
    return macros


def apply_macros(tex: str, macros, rounds: int = 8) -> str:
    by_name = {}
    for m in macros:
        by_name[m.name] = m
    if not by_name:
        return tex
    for _ in range(rounds):
        changed = False
        i = 0
        out = []
        n = len(tex)
        while i < n:
            if tex[i] != "\\":
                out.append(tex[i])
                i += 1
                continue
            name, j = parse_command_name(tex, i)
            mac = by_name.get(name or "")
            if not mac:
                out.append(tex[i:j])
                i = j
                continue
            k = j
            args = []
            ok = True
            start_arg = 0
            if mac.optional_default is not None:
                opt, k2 = parse_bracketed(tex, k)
                if opt is None:
                    args.append(mac.optional_default)
                else:
                    args.append(opt)
                    k = k2
                start_arg = 1
            for _a in range(start_arg, mac.n_args):
                k = skip_ws(tex, k)
                if k < n and tex[k] == "{":
                    arg, k = parse_braced(tex, k)
                    args.append(arg if arg is not None else "")
                elif k < n and tex[k] == "\\":
                    nm, k2 = parse_command_name(tex, k)
                    args.append(tex[k:k2])
                    k = k2
                elif k < n:
                    args.append(tex[k])
                    k += 1
                else:
                    ok = False
                    break
            if not ok:
                out.append(tex[i:j])
                i = j
                continue

            def subst(m):
                if m.group(0) == "##":
                    return "#"
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(args):
                    return args[idx]
                return m.group(0)

            body = re.sub(r"##|#([1-9])", subst, mac.body)
            out.append(body)
            i = k
            changed = True
        tex = "".join(out)
        if not changed:
            break
    return tex




def strip_macro_defs(tex: str) -> str:
    """收集完宏之后删掉 \\newcommand / \\DeclareMathOperator 定义，避免展开时改写定义本身。"""
    i = 0
    out = []
    n = len(tex)
    drop = {
        "newcommand", "renewcommand", "providecommand",
        "DeclareRobustCommand", "DeclareMathOperator",
    }
    while i < n:
        if tex[i] != "\\":
            out.append(tex[i])
            i += 1
            continue
        name, j = parse_command_name(tex, i)
        if name not in drop:
            out.append(tex[i:j])
            i = j
            continue
        jj = skip_ws(tex, j)
        if jj < n and tex[jj] == "*":
            jj += 1
        # name
        arg, k = parse_braced(tex, jj)
        if arg is None:
            _, k = parse_command_name(tex, skip_ws(tex, jj))
        # [n][def]{body}
        _, k2 = parse_bracketed(tex, k)
        if k2 != k:
            k = k2
            _, k3 = parse_bracketed(tex, k)
            if k3 != k:
                k = k3
        body, k4 = parse_braced(tex, k)
        if body is None:
            out.append(tex[i:j])
            i = j
            continue
        i = k4  # drop the whole definition
        out.append("%\n")  # 留个换行，避免把前后粘在一起
    return "".join(out)


def rewrite_known(tex: str) -> str:
    """把 pandoc 数学引擎不认识的常见命令改成等价 TeX。"""

    def repl_leftidx(s: str) -> str:
        i = 0
        out = []
        n = len(s)
        while i < n:
            if s.startswith("\\leftidx", i) and (i + 8 == n or not s[i + 8].isalpha()):
                a, j = parse_braced(s, i + 8)
                b, j2 = parse_braced(s, j)
                if a is not None and b is not None:
                    left = a[1:] if a.startswith("^") else a
                    out.append("{}^{" + left + "}{" + b + "}")
                    i = j2
                    continue
            out.append(s[i])
            i += 1
        return "".join(out)

    def drop_textcolor(s: str) -> str:
        i = 0
        out = []
        n = len(s)
        while i < n:
            if s.startswith("\\textcolor", i) and (i + 10 == n or not s[i + 10].isalpha()):
                k = i + 10
                _, k = parse_bracketed(s, k)
                c, k = parse_braced(s, k)
                b, k2 = parse_braced(s, k)
                if b is not None:
                    out.append(b)
                    i = k2
                    continue
            if s.startswith("\\colorbox", i) and (i + 9 == n or not s[i + 9].isalpha()):
                k = i + 9
                _, k = parse_bracketed(s, k)
                _, k = parse_braced(s, k)
                b, k2 = parse_braced(s, k)
                if b is not None:
                    out.append(b)
                    i = k2
                    continue
            if s.startswith("\\color", i) and (i + 6 == n or not s[i + 6].isalpha()):
                k = i + 6
                _, k = parse_bracketed(s, k)
                _, k2 = parse_braced(s, k)
                i = k2 if k2 > k else i + 6
                continue
            out.append(s[i])
            i += 1
        return "".join(out)

    def ieee_parstart(s: str) -> str:
        drop_names = {
            "IEEEoverridecommandlockouts", "IEEEpeerreviewmaketitle",
            "IEEEdisplaynontitleabstractindextext", "IEEEkeywords",
            "overrideIEEEmargins", "markboth", "IEEEauthorblockN",
            "IEEEauthorblockA", "IEEEauthorrefmark", "IEEEpubidadjcol",
        }
        i = 0
        out = []
        n = len(s)
        while i < n:
            if s[i] == "\\":
                name, j = parse_command_name(s, i)
                if name == "IEEEPARstart":
                    a, k = parse_braced(s, j)
                    b, k2 = parse_braced(s, k)
                    if a is not None and b is not None:
                        out.append(a + b)
                        i = k2
                        continue
                if name in drop_names:
                    k = j
                    for _ in range(3):
                        _, k2 = parse_bracketed(s, k)
                        arg, k3 = parse_braced(s, k2 if k2 != k else k)
                        if arg is None:
                            break
                        k = k3
                    i = k
                    continue
            out.append(s[i])
            i += 1
        return "".join(out)

    def drop_ensuremath(s: str) -> str:
        i = 0
        out = []
        n = len(s)
        while i < n:
            if s.startswith("\\ensuremath", i) and (i + 11 == n or not s[i + 11].isalpha()):
                b, j = parse_braced(s, i + 11)
                if b is not None:
                    out.append(b)
                    i = j
                    continue
            out.append(s[i])
            i += 1
        return "".join(s) if False else "".join(out)

    tex = repl_leftidx(tex)
    tex = drop_textcolor(tex)
    tex = ieee_parstart(tex)
    tex = re.sub(r"\\bm\s*\{", r"\\boldsymbol{", tex)
    tex = drop_ensuremath(tex)
    return tex



def unwrap_boxes_and_acronyms(tex: str) -> str:
    """拆掉 resizebox/scalebox（pandoc 遇它们常丢掉整张表），并把 acronym 命令收成简称。"""
    from .util import parse_braced, parse_bracketed, parse_command_name

    def take_cmd_body(s, i, cmd, n_braced):
        token = "\\" + cmd
        L = len(token)
        if not (s.startswith(token, i) and (i + L == len(s) or not s[i + L].isalpha())):
            return None, i
        k = i + L
        _, k = parse_bracketed(s, k)
        for _n in range(n_braced):
            arg, k2 = parse_braced(s, k)
            if arg is None:
                return None, i
            k = k2
            body = arg  # last braced is the body
        return body, k

    i = 0
    out = []
    n = len(tex)
    while i < n:
        body, k = take_cmd_body(tex, i, "resizebox", 3)  # {w}{h}{body}
        if body is not None:
            out.append(body)
            i = k
            continue
        body, k = take_cmd_body(tex, i, "scalebox", 2)
        if body is not None:
            out.append(body)
            i = k
            continue
        if tex.startswith("\\adjustbox", i) and (i + 10 == n or not tex[i + 10].isalpha()):
            k = i + 10
            _, k = parse_bracketed(tex, k)
            body, k2 = parse_braced(tex, k)
            if body is not None:
                out.append(body)
                i = k2
                continue
        if tex[i] == "\\":
            name, j = parse_command_name(tex, i)
            if name in {"ac", "acf", "acs", "acl", "aclu", "acsu", "Ac", "Acf", "Acs"}:
                arg, k = parse_braced(tex, j)
                if arg is not None:
                    out.append(arg)
                    i = k
                    continue
        out.append(tex[i])
        i += 1
    return "".join(out)

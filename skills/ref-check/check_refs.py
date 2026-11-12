#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考文献真伪核查：对照 Crossref / OpenAlex / Europe PMC，逐条判断是否真实存在。

只用 Python 标准库，不需要 API key。查不到时绝不编造替代条目。
脚本会把题名、DOI、PMID 发送到 Crossref、OpenAlex、Europe PMC 查询，不上传全文。

用法：
  python3 check_refs.py 我的文献.txt
  python3 check_refs.py 我的文献.txt -o report.html
  python3 check_refs.py --json report.json --md report.md 我的文献.txt
"""

from __future__ import annotations

import argparse
import os
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

UA_DEFAULT = "RefCheck/1.0 (local citation verifier; mailto:refcheck@localhost)"
CROSSREF = os.environ.get("REFCHECK_CROSSREF_BASE", "https://api.crossref.org").rstrip("/")
OPENALEX = os.environ.get("REFCHECK_OPENALEX_BASE", "https://api.openalex.org").rstrip("/")
EUROPEPMC = os.environ.get(
    "REFCHECK_EUROPEPMC_BASE",
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
)
HTTP_TIMEOUT = int(os.environ.get("REFCHECK_HTTP_TIMEOUT", "30"))

# 题名相似度阈值
STRONG_TITLE = 0.86
RELATED_TITLE = 0.70

# 这些 Crossref 类型容易抢在正刊前面，需要降权
LOW_VALUE_TYPES = {
    "dataset",
    "peer-review",
    "component",
    "grant",
    "journal-issue",
}
LOW_VALUE_TITLE_PREFIXES = (
    "faculty opinions recommendation of",
    "review for ",
    "author correction:",
    "publisher correction:",
    "erratum:",
)
LOW_VALUE_CONTAINERS = (
    "faculty opinions",
)

STATUS_ZH = {
    "verified": "已验证",
    "field_mismatch": "信息部分不符",
    "not_found": "查无此文",
    "suspected_fabricated": "疑似编造",
    "error": "核查失败/无法下结论",
}

FIELD_ZH = {
    "title": "题名",
    "authors": "作者",
    "year": "年份",
    "journal": "期刊/会议",
    "volume": "卷号",
    "issue": "期号",
    "pages": "页码",
    "doi": "DOI",
    "pmid": "PMID",
}


# ---------------------------------------------------------------------------
# 文本规范化与相似度
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_THE_RE = re.compile(r"\b(the|a|an|of|and|in|on|for|to|with)\b")


def norm_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\$[^$]*\$", " ", s)
    s = (
        s.lower()
        .replace("–", "-")
        .replace("—", "-")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    s = _PUNCT_RE.sub(" ", s)
    s = _THE_RE.sub(" ", s)
    return " ".join(s.split())


def token_set(s: str) -> set[str]:
    return set(norm_text(s).split())


def title_similarity(a: str | None, b: str | None) -> float:
    """综合序列比、词集合比，以及短题名是否为长题名的前缀/子集。"""
    if not a or not b:
        return 0.0
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jacc = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 0.0
    # 短题名是长题名前缀（常见于副标题被省略或被补上）
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    prefix = SequenceMatcher(None, short, long_[: len(short) + 8]).ratio() if short else 0.0
    containment_score = 0.0
    if ta and tb:
        smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        # 短题名几乎全部词落在长题名中，且短题名足够长，才视为“副标题被省略”
        if smaller and len(smaller) >= 6 and (len(smaller & larger) / len(smaller)) >= 0.9:
            containment_score = 0.92
    return max(seq, jacc, prefix * 0.98, containment_score)


def is_weak_title(title: str | None, raw: str | None = None) -> bool:
    """过短、或明显只是整段书目里的一个片段（如题名中段的引号短语）。"""
    nt = norm_text(title)
    if not nt:
        return True
    rem = norm_text(bibliographic_remainder(raw or "")) if raw else ""
    raw_n = norm_text(raw or "")
    short = len(nt) < 16 or len(nt.split()) <= 3
    if not short:
        return False
    longer = rem or raw_n
    if longer and len(longer) > len(nt) + 20:
        return True
    if raw_n and len(raw_n) <= len(nt) + 15:
        return False
    return True


def record_supported_by_cite(cited: "ParsedRef", rec: "Record | None") -> bool:
    """原文或书目残余能否支持「就是这条库记录」，而不只看可能解析错的短题名。"""
    if not rec or not rec.title:
        return False
    keys = []
    if cited.title and not is_weak_title(cited.title, cited.raw):
        keys.append(cited.title)
    rem = bibliographic_remainder(cited.raw or "")
    if rem:
        keys.append(rem)
    if cited.raw:
        keys.append(cited.raw)
    rec_n = norm_text(rec.title)
    for k in keys:
        if title_similarity(k, rec.title) >= 0.75:
            return True
        kn = norm_text(k)
        if rec_n and len(rec_n) >= 16 and rec_n in kn:
            return True
    return False


def cjk_char_bag(s: str | None) -> str:
    chars = re.findall(r"[\u4e00-\u9fff]", s or "")
    return "".join(sorted(chars)) if len(chars) >= 2 else ""


def protect_abbrev_periods(s: str) -> str:
    """避免题名里的 Phys. Rev. 或方括号内句点被当成「题名结束」。"""
    sentinel = "⁄"
    def _in_brackets(m: re.Match) -> str:
        return m.group(0).replace(".", sentinel)
    s = re.sub(r"\[[^\]]*\]", _in_brackets, s)
    def _abbrev(m: re.Match) -> str:
        word = m.group(1)
        # et al. 是作者段结束符，保护句点后仍保留分段句点
        if word.lower() == "al":
            return word + sentinel + "."
        return word + sentinel
    s = re.sub(
        r"\b(Phys|Rev|Prof|Dr|Mr|Ms|Mrs|St|Vol|No|Nos|al|eds?|Ed|U\.S|Inc|Ltd|Jr|Sr|Fig|Eq)\.",
        _abbrev,
        s,
        flags=re.I,
    )
    # 文摘号/短编号（P354. S12.）不是题名结束句点
    def _absnum(m: re.Match) -> str:
        return m.group(1) + sentinel
    s = re.sub(r"\b([A-Z]\d{2,4}|[A-Z]{2,3}\d{1,4})\.", _absnum, s)
    return s


def unprotect_abbrev_periods(s: str) -> str:
    return s.replace("⁄", ".")


def year_of(date_parts) -> int | None:
    try:
        return int(date_parts["date-parts"][0][0])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def norm_doi(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.I)
    s = s.strip().rstrip(".").lower()
    if s.startswith("doi:"):
        s = s[4:].strip()
    return s or None


def clean_biblio_field(v) -> str | None:
    """把库里的字符串 null/none 当成缺字段，而不是卷号。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or NULL_TOKEN_RE.fullmatch(s):
        return None
    return s


def norm_pages(s: str | None) -> str | None:
    if not s:
        return None
    s = s.replace("–", "-").replace("—", "-").replace(" ", "")
    return s.lower() or None


def pages_compatible(a: str | None, b: str | None) -> bool:
    """866-878 与 866-878.e1、27-27 与 27 视为同一页码。"""
    na, nb = norm_pages(a), norm_pages(b)
    if not na or not nb:
        return True
    if na == nb:
        return True
    def stem(s: str) -> str:
        s = re.sub(r"\.e\d+$", "", s, flags=re.I)
        m = re.fullmatch(r"(\d+(?:\.\d+)?)-(\1)", s)
        return m.group(1) if m else s
    sa, sb = stem(na), stem(nb)
    return sa == sb or sa == nb or sb == na


_NAME_PARTICLES = {
    "van", "von", "de", "der", "den", "da", "di", "do", "dos", "du",
    "la", "le", "del", "della", "dello", "st", "ste", "ter", "bin",
    "al", "el", "ibn", "mac", "mc",
}


def _significant_name_tokens(text: str) -> list[str]:
    """去掉缩写首字母、et al 和介词后的显著单词。"""
    out: list[str] = []
    for p in re.split(r"\s+", text.strip()):
        tok = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ\u4e00-\u9fff\-']", "", p).lower()
        tok = tok.strip("-'")
        if not tok or tok in {"and", "et", "al", "jr", "sr", "ii", "iii", "iv"}:
            continue
        if len(tok) == 1:  # A. / D. 这类缩写首名
            continue
        if tok in _NAME_PARTICLES:
            continue
        out.append(tok)
    return out


def family_candidates(raw: str, *, both_ends: bool = False) -> set[str]:
    """从一个作者字符串抽出可能的姓。

    引用常见「Vaswani, A.」或「A. Vaswani」；库中记录常见「Ashish Vaswani」
    （名在前）或 Crossref 的「Vaswani Ashish」（姓在前）。缩写首名应兼容全名。
    both_ends=True 时把首尾显著词都当作候选姓（用于库中记录）。
    """
    raw = (raw or "").strip()
    if not raw:
        return set()
    compact = re.sub(r"[\s,;，、]+", "", raw)
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", compact):
        return {compact}
    # 库中偶发把多名中文作者挤进同一个 family 字段（逗号、顿号或空格分隔）
    if re.search(r"[\u4e00-\u9fff]", raw):
        cjk_parts = []
        for p in re.split(r"[,;，、;；\s]+", raw):
            p = re.sub(r"[\s]*[\(（]?(?:1[89]\d{2}|20\d{2})[\)）]?[\s.。]*$", "", p).strip()
            chars = "".join(re.findall(r"[\u4e00-\u9fff]", p))
            if 2 <= len(chars) <= 4 and not re.search(r"[A-Za-z]{3,}", p):
                cjk_parts.append(chars)
        if len(cjk_parts) >= 2:
            return set(cjk_parts)
    if "," in raw.replace("，", ","):
        family = raw.replace("，", ",").split(",")[0].strip()
        toks = _significant_name_tokens(family)
        return {toks[-1]} if toks else set()
    # Vancouver「Shoemaker WR」「Mishra AK」：末词是缩写首名，不是姓
    parts = re.split(r"\s+", raw)
    last_raw = re.sub(r"[^A-Za-z]", "", parts[-1]) if parts else ""
    if last_raw.isalpha() and last_raw.isupper() and 1 <= len(last_raw) <= 4 and len(parts) >= 2:
        raw_for_toks = " ".join(parts[:-1])
        toks = _significant_name_tokens(raw_for_toks) or _significant_name_tokens(raw)
    else:
        toks = _significant_name_tokens(raw)
    if not toks:
        return set()
    # 一条字符串里挤进了多个姓名（库中偶发把两名作者写进同一字段）时，
    # 显著词都保留，避免只取末词而丢掉真正的姓。
    if len(toks) >= 3:
        return set(toks)
    if both_ends and len(toks) >= 2:
        return {toks[0], toks[-1]}
    return {toks[-1]}


def last_names(authors: list[str] | None, *, both_ends: bool = False) -> set[str]:
    names: set[str] = set()
    for raw in authors or []:
        names |= family_candidates(raw, both_ends=both_ends)
    return names


def journal_similar(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True  # 缺一边不当作不符
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return True
    if na == nb or na in nb or nb in na:
        return True
    if title_similarity(a, b) >= 0.72:
        return True
    # 简写 vs 全称：用首字母
    def initials(s: str) -> str:
        return "".join(w[0] for w in norm_text(s).split() if w)
    ia, ib = initials(a), initials(b)
    if ia and ib and (ia == ib or ia in ib or ib in ia) and min(len(ia), len(ib)) >= 3:
        return True
    return False


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
PMID_RE = re.compile(r"\bPMID\s*[:：]?\s*(\d{5,9})", re.I)
YEAR_RE = re.compile(r"(?:\((1[89]\d{2}|20\d{2})\)|(?:^|[^\d])(1[89]\d{2}|20\d{2})(?:[^\d]|$))")
VOL_ISSUE_RE = re.compile(
    r"\b(\d{1,5})\s*[\(（]\s*"
    r"([A-Za-z]?\d{1,5}(?:[_-][A-Za-z0-9]+)?(?:\s*[-–—/]\s*[A-Za-z]?\d{1,5}(?:[_-][A-Za-z0-9]+)?)?"
    r"(?:\s*[\(（]\s*\d{1,5}\s*[\)）])?)"
    r"\s*[\)）]"
)
PAGES_RE = re.compile(r"\b(?:pp?\.\s*)?(\d{1,6}(?:\.\d+)?)\s*[-–—]\s*(\d{1,6}(?:\.\d+)?)\b")
NULL_ISSUE_RE = re.compile(r"(?i)\b(?:null|none|n/?a|undefined)\s*[\(（]\s*([A-Za-z]?\d{1,5})\s*[\)）]")
NULL_TOKEN_RE = re.compile(r"(?i)^(?:null|none|n/?a|na|undefined|nil)$")
JUNK_VOL_IN_JOURNAL_RE = re.compile(r"[,，]?\s*(?:null|none|n/?a|undefined)\s*[\(（][^\)）]*[\)）]", re.I)
SPLIT_NUM_RE = re.compile(
    r"(?m)^\s*(?:\[\d+\]|\d+\s*[\.\)、]|（\d+）)\s+"
)


@dataclass
class ParsedRef:
    raw: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    title: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    pmid: str | None = None
    language_hint: str = "en"  # en | zh


def strip_tags(s: str | None) -> str | None:
    if not s:
        return s
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", "", s)).strip() or None


def looks_cjk(s: str) -> bool:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s or ""))
    return cjk >= 4


def split_references(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    # 去掉常见标题行
    lines = text.split("\n")
    if lines and re.fullmatch(r"\s*(参考文献|references|works cited|bibliography)\s*[:：]?\s*", lines[0], re.I):
        text = "\n".join(lines[1:]).strip()
    if SPLIT_NUM_RE.search(text):
        parts = SPLIT_NUM_RE.split(text)
        # split 会保留分隔符两侧，先按行切再拼
        blocks: list[str] = []
        current: list[str] = []
        for line in text.split("\n"):
            if SPLIT_NUM_RE.match(line) and current:
                blocks.append(" ".join(x.strip() for x in current if x.strip()))
                current = [SPLIT_NUM_RE.sub("", line, count=1)]
            elif SPLIT_NUM_RE.match(line):
                current = [SPLIT_NUM_RE.sub("", line, count=1)]
            else:
                current.append(line)
        if current:
            blocks.append(" ".join(x.strip() for x in current if x.strip()))
        return [b.strip(" ;,;；") for b in blocks if len(b.strip()) > 8]
    # 空行分段
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if len(p) > 8]
    if len(paras) >= 2:
        return paras
    # 单段：按行
    rows = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]
    if len(rows) >= 2 and all(len(r) > 20 for r in rows):
        return rows
    return [text] if text else []



APA_AUTHOR_RE = re.compile(
    r"([A-ZÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\-]+|[\u4e00-\u9fff]{2,4}),\s*"
    r"((?:[A-Z]\.?(?:-[A-Z]\.?)?\s*){1,3})"
)
VANC_AUTHOR_RE = re.compile(
    r"([A-ZÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\-]+|[\u4e00-\u9fff]{2,4})\s+((?:[A-Z]\.\s*){1,3})"
)


def parse_author_string(head: str) -> list[str]:
    head = re.sub(r"^\[\d+\]\s*", "", head).strip()
    head = re.sub(r"\s+and\s+", ", ", head, flags=re.I)
    head = re.sub(r"\s*&\s*", ", ", head)
    head = re.sub(r",?\s*(et al\.?|等)\s*", ", ", head, flags=re.I)
    head = head.strip(" .,;，。；&")
    if not head:
        return []
    # IEEE：「S. Ullrich, K. Thriene, and K. Michels」
    ieee = re.findall(
        r"\b((?:[A-Z]\.\s*)+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'\-]+)",
        head,
    )
    if len(ieee) >= 2 and looks_cjk(head) is False:
        return [a.strip() for a in ieee][:12]
    if looks_cjk(head) and not re.search(r"[A-Za-z]{3,}", head):
        names = []
        for x in re.split(r"[、,，;；]", head):
            x = re.sub(r"[\s]*[\(（]?(?:1[89]\d{2}|20\d{2})[\)）]?[\s.。]*$", "", x)
            x = x.strip(" .,;，。；" + "\u201c\u201d\u300c\u300d")
            if x and len(x) < 40 and not re.fullmatch(r"vols?\.?", x, re.I):
                names.append(x)
        return names
    # Vancouver 无点缩写必须放在 APA 之前，否则 "Kesselheim AS, Cresswell K" 会被吃成 "AS, C"
    parts = [x.strip() for x in re.split(r"\s*,\s*", head) if x.strip()]
    vanc_compact = []
    for part in parts:
        part = re.sub(r"\.$", "", part).strip()
        m = re.fullmatch(
            r"([A-ZÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\-]+|[\u4e00-\u9fff]{2,4})\s+([A-Z]{1,4})",
            part,
        )
        if m:
            vanc_compact.append(f"{m.group(1)} {m.group(2)}")
    # 允许末项是「等」被去掉后，绝大多数片段都是 Vancouver 缩写
    if vanc_compact and len(vanc_compact) >= max(1, len(parts) - 1) and len(vanc_compact) >= len(parts) * 0.6:
        return vanc_compact[:12]
    found = [f"{m.group(1)}, {m.group(2).strip()}" for m in APA_AUTHOR_RE.finditer(head)]
    if found:
        return found[:12]
    found = [f"{m.group(1)} {m.group(2).strip()}" for m in VANC_AUTHOR_RE.finditer(head)]
    if found:
        return found[:12]
    bits = re.split(r"[;；、/]", head)
    cleaned = []
    for b in bits:
        b = b.strip(" .")
        if b and not re.fullmatch(r"\d+", b) and len(b) < 80:
            cleaned.append(b)
    if cleaned and all(len(c.split()) <= 6 or looks_cjk(c) for c in cleaned[:8]):
        return cleaned[:12]
    return []



def bibliographic_remainder(raw: str) -> str:
    """去掉 DOI、URL、PMID 后剩下的书目文字。"""
    s = DOI_RE.sub(" ", raw or "")
    s = PMID_RE.sub(" ", s)
    s = re.sub(r"https?://\S+", " ", s, flags=re.I)
    s = re.sub(r"\b(?:doi|pmid)\s*[:：]?\s*", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" .;,:/")
    return s


def is_identifier_only(ref: ParsedRef) -> bool:
    """输入实质上只是 DOI、PMID 或指向 DOI 的 URL，没有独立题名。"""
    if not (ref.doi or ref.pmid):
        return False
    if ref.title and len(norm_text(ref.title)) >= 8:
        return False
    return len(bibliographic_remainder(ref.raw)) < 8


def fill_from_bibtex(raw: str, ref: ParsedRef) -> None:
    """用 BibTeX 字段补全尚未抽出的题名、作者、年份等。"""
    if not re.search(r"@\w+\s*\{", raw or ""):
        return

    def field(name: str) -> str | None:
        m = re.search(
            rf"\b{name}\s*=\s*(?:{{([^{{}}]+)}}|\"([^\"]+)\"|(\d+))",
            raw,
            re.I,
        )
        if not m:
            return None
        return (m.group(1) or m.group(2) or m.group(3) or "").strip() or None

    title = field("title")
    if title and not ref.title:
        ref.title = title
    authors = field("author")
    if authors:
        parsed_au = [a.strip() for a in re.split(r"\s+and\s+", authors, flags=re.I) if a.strip()][:12]
        if parsed_au:
            ref.authors = parsed_au
    year = field("year")
    if year and year.isdigit() and not ref.year:
        y = int(year)
        if 1900 <= y <= 2026:
            ref.year = y
    journal = field("journal") or field("booktitle")
    if journal and not ref.journal:
        ref.journal = journal
    if field("volume") and not ref.volume:
        ref.volume = field("volume")
    if field("number") and not ref.issue:
        ref.issue = field("number")
    pages = field("pages")
    if pages and not ref.pages:
        ref.pages = pages.replace("--", "-").replace("–", "-").replace(" ", "")
    doi = field("doi")
    if doi and not ref.doi:
        ref.doi = norm_doi(doi)


def parse_one(raw: str) -> ParsedRef:
    raw = strip_tags(re.sub(r"\s+", " ", raw).strip()) or ""
    ref = ParsedRef(raw=raw)
    m = DOI_RE.search(raw)
    if m:
        ref.doi = norm_doi(m.group(1).rstrip(").,;，。；"))
    m = PMID_RE.search(raw)
    if m:
        ref.pmid = m.group(1)
    # 年份：独立的「(2017)」优先；题名里的「(2008-2015)」或未加括号的「1998–2017」不当作出版年
    range_years = set()
    for rm in re.finditer(
        r"(?<!\d)(1[89]\d{2}|20\d{2})\s*[-–—]\s*(1[89]\d{2}|20\d{2})(?!\d)", raw
    ):
        range_years.add(int(rm.group(1)))
        range_years.add(int(rm.group(2)))
    ym = re.search(r"[\(（](1[89]\d{2}|20\d{2})[\)）]", raw)
    if ym and int(ym.group(1)) not in range_years:
        ref.year = int(ym.group(1))
    else:
        tail = DOI_RE.sub(" ", raw)
        tail = re.sub(r"https?://\S+", " ", tail, flags=re.I)
        near_end = [
            int(y)
            for y in re.findall(r"\.\s*(1[89]\d{2}|20\d{2})\b", tail)
            if 1900 <= int(y) <= 2026 and int(y) not in range_years
        ]
        if near_end:
            ref.year = near_end[-1]
        else:
            ieee_y = re.search(
                r"\b(?:vol\.|no\.|nos\.|pp?\.)[^\n]{0,60}?,\s*(1[89]\d{2}|20\d{2})\b",
                tail,
                re.I,
            )
            if not ieee_y:
                ieee_y = re.search(
                    r",\s*(1[89]\d{2}|20\d{2})(?:\s*[,.]\s*(?:doi|https?://)|\s*$)",
                    tail,
                    re.I,
                )
            if ieee_y and int(ieee_y.group(1)) not in range_years and 1900 <= int(ieee_y.group(1)) <= 2026:
                ref.year = int(ieee_y.group(1))
            else:
                years = [
                    int(y)
                    for y in re.findall(r"\b(1[89]\d{2}|20\d{2})\b", tail)
                    if 1900 <= int(y) <= 2026 and int(y) not in range_years
                ]
                if years:
                    ref.year = years[0]
    # 体积、页码必须在去掉 DOI/URL 之后提取，否则 10.1016/s0140-6736(16)30392-0 会被当成卷 6736 期 16
    body = bibliographic_remainder(raw)
    vm = VOL_ISSUE_RE.search(body)
    if vm:
        ref.volume, ref.issue = vm.group(1), vm.group(2)
    elif (nm := NULL_ISSUE_RE.search(body)):
        ref.issue = nm.group(1)
    ranges = list(PAGES_RE.finditer(body))
    # 题名里的年份区间（2008-2015）不是页码
    def _year_range(m: re.Match) -> bool:
        try:
            a, b = int(m.group(1)), int(m.group(2))
        except ValueError:
            return False
        return 1900 <= a <= 2026 and 1900 <= b <= 2026 and 0 <= (b - a) <= 80
    ranges = [m for m in ranges if not _year_range(m)]
    # 「Journal, 7-8, 1-9」：前一段像卷号，后一段才是页码
    if not ref.volume and len(ranges) >= 2:
        ref.volume = f"{ranges[0].group(1)}-{ranges[0].group(2)}"
        ref.pages = f"{ranges[-1].group(1)}-{ranges[-1].group(2)}"
    elif ranges:
        ref.pages = f"{ranges[-1].group(1)}-{ranges[-1].group(2)}"
    # APA：「刊名, 卷, 论文号/页码」或「刊名, 卷(期), 108.11-108.11」
    # 不要把行尾论文号 1188 当成卷，也不要把 108.11-108.11 拆成 11-108
    apa_art = re.search(
        r",\s*(\d{1,5})(?:\s*[\(（]([^\)）]{1,30})[\)）])?\s*,\s*"
        r"([A-Za-z]?\d{1,6}(?:\.\d+)?(?:\s*[-–—]\s*[A-Za-z]?\d{1,6}(?:\.\d+)?)?)"
        r"(?:\s*(?:\.|$|https?://|doi))",
        body,
        re.I,
    )
    def _is_year_token(x: str) -> bool:
        return bool(re.fullmatch(r"(?:1[89]\d{2}|20\d{2})", x or ""))
    if apa_art and not _is_year_token(apa_art.group(3).replace(" ", "")):
        first, iss, second = apa_art.group(1), apa_art.group(2), apa_art.group(3)
        second_n = re.sub(r"\s+", "", second.replace("–", "-").replace("—", "-"))
        # GB/T：「刊名, 2022, 15」里第一个数字是出版年，第二个才是卷号
        year_then_vol = _is_year_token(first) and (ref.year is None or int(first) == ref.year)
        if year_then_vol:
            if not ref.volume:
                ref.volume = second_n.split("-")[0] if "-" in second_n and not iss else second_n
            if iss and not ref.issue:
                ref.issue = iss.strip()
        else:
            if not ref.volume or ref.volume in {second_n, second_n.split("-")[0], second}:
                ref.volume = first
            if iss and not ref.issue:
                ref.issue = iss.strip()
            if not ref.pages:
                ref.pages = second_n
    if not ref.volume:
        # APA/GB：刊名后只有卷号、没有期号，如「… Biology, 14. https://doi.org/…」
        # bibliographic_remainder 会去掉末尾句点，所以也要匹配行尾卷号
        vm2 = re.search(
            r",\s*(\d{1,4})(?:\s*[-–—]\s*(\d{1,4}))?(?:\s*\.(?:\s|$|https?://|doi)|\s*$)",
            body,
            re.I,
        )
        if vm2:
            cand = f"{vm2.group(1)}-{vm2.group(2)}" if vm2.group(2) else vm2.group(1)
            # 「null(43), 45-82」里的 45-82 已是页码，不能再当成卷号
            if not ref.pages or cand != ref.pages:
                ref.volume = cand
    # IEEE / MLA：vol. 5, no. 2, pp. 21-41。显式 vol. 优先于行尾被误当成卷号的年份。
    vm3 = re.search(r"\bvols?\.\s*(\d{1,5})\b", body, re.I)
    if vm3:
        ref.volume = vm3.group(1)
    if not ref.issue:
        im3 = re.search(r"\b(?:no|nos|number)\.\s*([A-Za-z]?\d{1,5}[A-Za-z0-9_\-]*)\b", body, re.I)
        if im3:
            ref.issue = im3.group(1)
    pm3 = re.search(
        r"\bpp?\.\s*([A-Za-z]?\d{1,6}(?:\.\d+)?(?:\s*[-–—]\s*[A-Za-z]?\d{1,6}(?:\.\d+)?)?)",
        body,
        re.I,
    )
    if pm3 and (not ref.pages or (ref.volume and ref.pages == ref.volume)):
        ref.pages = re.sub(r"\s+", "", pm3.group(1).replace("–", "-").replace("—", "-"))
    # 行尾「, 2021」在已有 vol./pp. 时不是卷号
    if ref.volume and re.fullmatch(r"(?:1[89]\d{2}|20\d{2})", ref.volume) and vm3:
        ref.volume = vm3.group(1)
    # 题名：先按书目结构，引号只作后补，以免把题名中段的 “hot Jupiter” 当成整条题名
    tm = re.search(r"《([^》]{6,})》", raw)
    if tm:
        ref.title = tm.group(1).strip()
    if not ref.title:
        # APA: (year). Title. Journal —— 先保护 Phys. Rev. 与方括号内句点
        protected = protect_abbrev_periods(raw)
        tm = re.search(
            r"[\(（](?:1[89]\d{2}|20\d{2})[\)）]\s*\.?\s*(.+?)\.\s+([A-Z《].+)$",
            protected,
        )
        if tm:
            ref.title = unprotect_abbrev_periods(tm.group(1)).strip()
            rest = unprotect_abbrev_periods(tm.group(2))
            j = re.split(r"[,，]\s*\d|\s+\d{1,4}\s*[\(（]|https?://|\b10\.\d{4}", rest, maxsplit=1)
            ref.journal = j[0].strip(" .,;；")
        else:
            tm = re.search(r"\.\s*([^.]{6,}?)\s*\[J\]\s*\.\s*([^,，]+)", raw)
            if tm:
                ref.title = tm.group(1).strip()
                ref.journal = tm.group(2).strip()
            elif looks_cjk(raw):
                m2 = re.search(
                    r"^(.+?)[。\.]\s*(.+?)[。\.]\s*(.+?)[,，]\s*(1[89]\d{2}|20\d{2})",
                    raw,
                )
                if m2:
                    ref.authors = re.split(r"[、,，;；/]| and ", m2.group(1))
                    ref.authors = [a.strip() for a in ref.authors if a.strip()]
                    ref.title = m2.group(2).strip()
                    ref.journal = m2.group(3).strip()
    # 中文或西文 APA：「(年). 题名. 刊名, 卷」——刊名不必以拉丁大写开头
    if not ref.title:
        tm = re.search(
            r"[\(（](1[89]\d{2}|20\d{2})[\)）]\s*\.?\s*(.+?)\.\s+(.+?)[,，]\s*\d",
            raw,
        )
        if tm and len(tm.group(2).strip()) >= 6:
            ref.title = tm.group(2).strip()
            if not ref.journal:
                ref.journal = tm.group(3).strip()
            if not ref.year:
                ref.year = int(tm.group(1))
    # Vancouver: Authors. Title. Journal. Year; vol: pages.
    if not ref.title:
        cleaned = bibliographic_remainder(protect_abbrev_periods(raw))
        vm = re.search(
            r"^(.+?)\.\s+(.+?)\.\s+(.+?)\.\s+(1[89]\d{2}|20\d{2})(?:\s+[A-Za-z]{3,9})?\s*(?:[;:]|\.\s*|$)",
            cleaned.strip(),
        )
        if vm and len(unprotect_abbrev_periods(vm.group(2)).strip()) >= 8:
            if not ref.authors:
                ref.authors = parse_author_string(unprotect_abbrev_periods(vm.group(1)))
            ref.title = unprotect_abbrev_periods(vm.group(2)).strip()
            if not ref.journal:
                ref.journal = unprotect_abbrev_periods(vm.group(3)).strip()
            if not ref.year:
                ref.year = int(vm.group(4))

    # IEEE / MLA / 中文带引号题名：先取引号内完整题名（含 ASCII 引号的中文 IEEE）
    qm = re.search(r"[“\"「](.+?)[”\"」]", raw)
    if qm:
        qt = qm.group(1).strip(" .,;，。；")
        ieee_like = bool(re.search(r"\bvols?\.", raw, re.I))
        if qt and len(qt) >= 6 and (looks_cjk(qt) or ieee_like or not is_weak_title(qt, raw)):
            if not ref.title or is_weak_title(ref.title, raw) or (ieee_like and looks_cjk(qt)):
                ref.title = qt
    # 引号题名只在结构解析失败时使用，且不得是整段书目里的短片段
    if not ref.title:
        if qm and len(qm.group(1).strip()) > 8 and not is_weak_title(qm.group(1), raw):
            ref.title = qm.group(1).strip(" .。")

    # 引号题名就位后，按「题名」后面的刊名重抽（避免先误抽「3, no」再留下错误刊名）
    if ref.title and ref.title in raw:
        after = raw.split(ref.title, 1)[-1]
        jm = re.search(
            r'^[,"\s「」“”]+([^,，]{2,80}?)\s*[,，]\s*(?:vol\.|vols\.|\d)',
            after,
            re.I,
        )
        if jm:
            cand = jm.group(1).strip(" .,;；" + "\"'" + "\u201c\u201d\u300c\u300d")
            if cand and not re.search(r"\bvols?\.", cand, re.I) and not re.fullmatch(r"\d+", cand):
                ref.journal = cand
        if ref.authors and any(
            (ref.title and ref.title in a) or re.search(r"\bvols?\.?\b", a, re.I) or a.strip(" \"'" + "\u201c\u201d") == ""
            for a in ref.authors
        ):
            ref.authors = []

    # 仅 DOI / 仅 URL / 仅 PMID：不要把标识符本身拆成「作者」
    remainder = bibliographic_remainder(raw)
    if (ref.doi or ref.pmid) and not ref.title and len(remainder) < 8:
        ref.authors = []
        # DOI 字符串里的数字不是出版年或卷期
        ref.year = None
        ref.volume = None
        ref.issue = None
        ref.pages = None
    # 作者：题名或年份之前的部分
    elif not ref.authors:
        head = raw
        if ref.title and ref.title in raw:
            head = raw.split(ref.title)[0]
        elif ref.year:
            head = re.split(r"[\(（]" + str(ref.year), raw, maxsplit=1)[0]
        ref.authors = parse_author_string(head)

    if not ref.journal and ref.title:
        # Vancouver: Title. Journal. Year;
        after = raw.split(ref.title, 1)[-1]
        jm = re.search(r"^[\s\.\"]+([^.,;，。]{3,80})[,.]", after)
        if jm:
            cand = jm.group(1).strip()
            if not re.search(r"\d{4}", cand):
                ref.journal = cand
    # BibTeX：@article{..., title={...}, author={...}, year={...}}
    fill_from_bibtex(raw, ref)

    # 只有题名、没有年份/DOI/PMID 时，整段都是题名，不拆作者，也不保留误抽的引号短题
    if not ref.year and not ref.doi and not ref.pmid:
        ref.title = raw.strip(" .")
        ref.authors = []
        ref.journal = None
        ref.volume = None
        ref.issue = None
        ref.pages = None
    if ref.authors:
        cleaned_au=[]
        junk= " .,;，。；\"'" + "\u201c\u201d\u300c\u300d"
        for a in ref.authors:
            a=a.strip(junk)
            if a and not re.fullmatch(r"vols?\.?", a, re.I):
                cleaned_au.append(a)
        ref.authors=cleaned_au
    if ref.title:
        ref.title = ref.title.strip(" .,;，；") or None
    if ref.journal:
        ref.journal = JUNK_VOL_IN_JOURNAL_RE.sub("", ref.journal).strip(" .,;；") or None
    ref.volume = clean_biblio_field(ref.volume)
    ref.issue = clean_biblio_field(ref.issue)
    # 以题名/刊名的文字为准，避免引用前后的中文说明把英文条目判成中文
    probe = " ".join(x for x in (ref.title, ref.journal) if x) or raw
    cjk_n = len(re.findall(r"[\u4e00-\u9fff]", probe))
    latin_n = len(re.findall(r"[A-Za-z]", probe))
    ref.language_hint = "zh" if cjk_n >= 4 and cjk_n >= latin_n else "en"
    return ref


def looks_complete(ref: ParsedRef) -> bool:
    if is_identifier_only(ref):
        return False
    has_people = bool(ref.authors) or bool(re.search(r"[A-Z][a-z]+|[一-龥]{2,}", ref.raw))
    has_source = bool(ref.journal) or bool(ref.doi) or bool(ref.pmid)
    has_year = ref.year is not None
    has_title = bool(ref.title) and len(ref.title) >= 8
    return bool(has_people and has_source and has_year and has_title)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def http_get_json(url: str, ua: str, timeout: int | None = None) -> dict[str, Any]:
    if timeout is None:
        timeout = HTTP_TIMEOUT
    last_err: HttpError | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = HttpError(f"HTTP {e.code} for {url}", status=e.code)
            if e.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_err from e
        except Exception as e:
            last_err = HttpError(f"{type(e).__name__}: {e}", status=None)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_err from e
    raise last_err or HttpError(f"request failed for {url}", status=None)


# ---------------------------------------------------------------------------
# 数据库记录
# ---------------------------------------------------------------------------

@dataclass
class Record:
    source: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    pmid: str | None = None
    typ: str | None = None
    url: str | None = None
    score: float = 0.0
    title_sim: float = 0.0

    def to_public(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def record_url(rec: Record) -> str | None:
    if rec.doi:
        return f"https://doi.org/{rec.doi}"
    if rec.pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{rec.pmid}/"
    return rec.url


def is_low_value(rec: Record) -> bool:
    typ = (rec.typ or "").lower()
    if typ in LOW_VALUE_TYPES:
        return True
    title = (rec.title or "").lower()
    if any(title.startswith(p) for p in LOW_VALUE_TITLE_PREFIXES):
        return True
    journal = (rec.journal or "").lower()
    if any(k in journal for k in LOW_VALUE_CONTAINERS):
        return True
    return False


def from_crossref(item: dict[str, Any]) -> Record:
    authors = []
    for a in item.get("author") or []:
        fam = (a.get("family") or "").strip()
        giv = (a.get("given") or "").strip()
        if fam or giv:
            authors.append(f"{fam} {giv}".strip())
    title = strip_tags((item.get("title") or [""])[0] or None)
    journal = (item.get("container-title") or [""])[0] or None
    year = year_of(item.get("published-print")) or year_of(item.get("published")) or year_of(item.get("issued"))
    doi = norm_doi(item.get("DOI"))
    pages = item.get("page")
    rec = Record(
        source="crossref",
        title=title,
        authors=authors,
        year=year,
        journal=journal,
        volume=clean_biblio_field(item.get("volume")),
        issue=clean_biblio_field(item.get("issue")),
        pages=clean_biblio_field(pages),
        doi=doi,
        typ=item.get("type"),
        url=f"https://doi.org/{doi}" if doi else item.get("URL"),
        score=float(item.get("score") or 0),
    )
    return rec


def from_openalex(item: dict[str, Any]) -> Record:
    authors = []
    for a in item.get("authorships") or []:
        name = ((a.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    loc = item.get("primary_location") or {}
    src = loc.get("source") or {}
    biblio = item.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    pages = None
    if first and last:
        pages = f"{first}-{last}"
    elif first:
        pages = str(first)
    doi = norm_doi(item.get("doi") or "")
    rec = Record(
        source="openalex",
        title=strip_tags(item.get("title") or item.get("display_name")),
        authors=authors,
        year=item.get("publication_year"),
        journal=src.get("display_name"),
        volume=clean_biblio_field(biblio.get("volume")),
        issue=clean_biblio_field(biblio.get("issue")),
        pages=clean_biblio_field(pages),
        doi=doi,
        typ=item.get("type"),
        url=(loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else item.get("id"))),
        pmid=None,
    )
    # OpenAlex ids sometimes include pmid
    ids = item.get("ids") or {}
    pmid = ids.get("pmid")
    if pmid:
        m = re.search(r"(\d+)$", str(pmid))
        if m:
            rec.pmid = m.group(1)
    return rec


def from_epmc(item: dict[str, Any]) -> Record:
    pages = item.get("pageInfo")
    doi = norm_doi(item.get("doi"))
    authors = []
    if item.get("authorString"):
        authors = [x.strip() for x in re.split(r"\s*;\s*", item["authorString"]) if x.strip()]
    return Record(
        source="europepmc",
        title=strip_tags(item.get("title")),
        authors=authors,
        year=int(item["pubYear"]) if item.get("pubYear") and str(item["pubYear"]).isdigit() else None,
        journal=item.get("journalTitle"),
        volume=item.get("journalVolume"),
        issue=item.get("issue"),
        pages=pages,
        doi=doi,
        pmid=str(item.get("pmid") or item.get("id") or ""),
        typ="journal-article",
        url=(f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{item.get('pmid')}/"),
    )


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self, mailto: str | None = None, delay: float = 0.4, use_s2: bool = False):
        mail = mailto or "refcheck@localhost"
        self.ua = f"RefCheck/1.0 (local citation verifier; mailto:{mail})"
        self.mailto = mail
        self.delay = delay
        self.last_call = 0.0
        self.use_s2 = use_s2
        self.errors: list[str] = []
        self.hard_failures: list[str] = []
        self.last_query_failed = False

    def _wait(self) -> None:
        dt = time.time() - self.last_call
        if dt < self.delay:
            time.sleep(self.delay - dt)
        self.last_call = time.time()

    def get(self, url: str) -> dict[str, Any]:
        self._wait()
        return http_get_json(url, self.ua)

    def _note_failure(self, where: str, err: HttpError, *, allow_404: bool = False) -> None:
        """404 视为「正常返回但无此记录」；超时 / 连接失败 / 429 / 5xx 记为硬失败。"""
        if allow_404 and err.status == 404:
            self.last_query_failed = False
            return
        self.last_query_failed = True
        msg = f"{where}: {err}"
        self.errors.append(msg)
        self.hard_failures.append(msg)

    def crossref_doi(self, doi: str) -> Record | None:
        self.last_query_failed = False
        url = f"{CROSSREF}/works/{urllib.parse.quote(doi)}"
        try:
            data = self.get(url)
            return from_crossref(data["message"])
        except HttpError as e:
            self._note_failure(f"Crossref DOI {doi}", e, allow_404=True)
            return None

    def crossref_biblio(self, query: str, rows: int = 5) -> list[Record]:
        self.last_query_failed = False
        url = f"{CROSSREF}/works?" + urllib.parse.urlencode(
            {"query.bibliographic": query, "rows": rows}
        )
        try:
            data = self.get(url)
            return [from_crossref(it) for it in data.get("message", {}).get("items") or []]
        except HttpError as e:
            self._note_failure("Crossref search", e)
            return []

    def openalex_doi(self, doi: str) -> Record | None:
        self.last_query_failed = False
        url = f"{OPENALEX}/works/doi:{doi}?mailto={urllib.parse.quote(self.mailto)}"
        try:
            data = self.get(url)
            return from_openalex(data)
        except HttpError as e:
            self._note_failure(f"OpenAlex DOI {doi}", e, allow_404=True)
            return None

    def openalex_search(self, query: str, per_page: int = 5) -> list[Record]:
        self.last_query_failed = False
        url = f"{OPENALEX}/works?" + urllib.parse.urlencode(
            {"search": query, "per-page": per_page, "mailto": self.mailto}
        )
        try:
            data = self.get(url)
            return [from_openalex(it) for it in data.get("results") or []]
        except HttpError as e:
            self._note_failure("OpenAlex search", e)
            return []

    def epmc_pmid(self, pmid: str) -> Record | None:
        self.last_query_failed = False
        q = f"EXT_ID:{pmid} AND SRC:MED"
        url = f"{EUROPEPMC}?" + urllib.parse.urlencode({"query": q, "format": "json"})
        try:
            data = self.get(url)
            hits = (data.get("resultList") or {}).get("result") or []
            if not hits:
                return None
            return from_epmc(hits[0])
        except HttpError as e:
            self._note_failure(f"Europe PMC PMID {pmid}", e)
            return None

    def epmc_search(self, query: str) -> list[Record]:
        self.last_query_failed = False
        url = f"{EUROPEPMC}?" + urllib.parse.urlencode(
            {"query": query, "format": "json", "pageSize": 5}
        )
        try:
            data = self.get(url)
            hits = (data.get("resultList") or {}).get("result") or []
            return [from_epmc(h) for h in hits]
        except HttpError as e:
            self._note_failure("Europe PMC search", e)
            return []


# ---------------------------------------------------------------------------
# 比对与判定
# ---------------------------------------------------------------------------

def looks_like_romanized_cjk_journal(name: str | None) -> bool:
    """无英文刊名标记、全是拉丁音节的刊名，更像中文刊名的拼音，而不是 Chin J Med 这类英文缩写。"""
    if not name or re.search(r"[\u4e00-\u9fff]", name):
        return False
    toks = [w for w in re.findall(r"[A-Za-z]+", name) if len(w) >= 2]
    if len(toks) < 2:
        return False
    markers = {
        "journal", "review", "letters", "proceedings", "transactions",
        "international", "research", "studies", "bulletin", "medicine",
        "medical", "med", "chin", "chinese", "asian", "european", "american",
        "british", "annals", "acta", "rev", "int", "sci", "science", "biol",
        "bio", "phys", "chem", "nurs", "health", "clinic", "clinical",
        "postgrad", "postgraduate", "j",
    }
    if any(w.lower() in markers for w in toks):
        return False
    return all(re.fullmatch(r"[A-Za-z]{2,10}", w) for w in toks)


def compare_fields(cited: ParsedRef, rec: Record) -> list[dict[str, Any]]:
    """返回不符字段列表（含双方取值）。期刊简写差异不记为不符。"""
    mismatches: list[dict[str, Any]] = []

    if cited.title and rec.title:
        sim = title_similarity(cited.title, rec.title)
        if sim < STRONG_TITLE:
            mismatches.append(
                {
                    "field": "title",
                    "cited": cited.title,
                    "found": rec.title,
                    "similarity": round(sim, 3),
                }
            )

    if cited.year and rec.year and cited.year != rec.year:
        mismatches.append({"field": "year", "cited": cited.year, "found": rec.year})

    if cited.authors and rec.authors:
        # 引用侧按「姓, 名」或末词取姓；库中记录同时接受「名 姓」和「姓 名」
        a, b = last_names(cited.authors), last_names(rec.authors, both_ends=True)
        cited_bags = {cjk_char_bag(x) for x in cited.authors if cjk_char_bag(x)}
        rec_bags = {cjk_char_bag(x) for x in rec.authors if cjk_char_bag(x)}
        first_cjk_ok = False
        first_bag = cjk_char_bag(cited.authors[0]) if cited.authors else ""
        if first_bag and first_bag in rec_bags:
            first_cjk_ok = True
        def _cjk_compact(text: str) -> str:
            return "".join(re.findall(r"[\u4e00-\u9fff]", text or ""))
        first_cjk = _cjk_compact(cited.authors[0]) if cited.authors else ""
        rec_cjk_blob = "".join(_cjk_compact(x) for x in rec.authors)
        cited_cjk_blob = "".join(_cjk_compact(x) for x in cited.authors)
        if first_cjk and rec_cjk_blob and first_cjk in rec_cjk_blob:
            first_cjk_ok = True
        jammed_ok = False
        if cited_cjk_blob and rec_cjk_blob:
            cs, rs = set(cited_cjk_blob), set(rec_cjk_blob)
            jaccard = len(cs & rs) / len(cs | rs)
            if jaccard >= 0.8 and first_cjk_ok:
                jammed_ok = True
        if jammed_ok:
            a, b = set(), set()  # 已确认同一组中文作者，跳过后面的拉丁姓比对
        if a and b:
            overlap = len(a & b) / len(a)
            first_fams = last_names(cited.authors[:1])
            first_fail = bool(first_fams) and not (first_fams & b) and not first_cjk_ok
            overlap_fail = overlap < 0.4 and not (cited_bags & rec_bags)
            if first_fail or overlap_fail:
                mismatches.append(
                    {
                        "field": "authors",
                        "cited": ", ".join(cited.authors[:6]),
                        "found": ", ".join(rec.authors[:6]),
                    }
                )
        elif first_cjk_ok:
            pass

    doi_locked = bool(cited.doi and rec.doi and norm_doi(cited.doi) == norm_doi(rec.doi))
    title_locked = bool(cited.title and rec.title and title_similarity(cited.title, rec.title) >= STRONG_TITLE)
    if cited.journal and rec.journal and not journal_similar(cited.journal, rec.journal):
        # DOI+题名锁定同一篇时，只忽略「同一刊的中英对照/缩写」，
        # 不能把 Nature 与 European Heart Journal 这种明显不同的刊名也放过去
        ignore = False
        if doi_locked and title_locked:
            cjk_a = bool(re.search(r"[\u4e00-\u9fff]", cited.journal))
            cjk_b = bool(re.search(r"[\u4e00-\u9fff]", rec.journal))
            if cjk_a != cjk_b and not (
                looks_like_romanized_cjk_journal(cited.journal)
                or looks_like_romanized_cjk_journal(rec.journal)
            ):
                # 一边中文、一边英文刊名缩写，可视为同一刊；
                # 一边中文、一边另一刊的拼音（如 中华内科杂志 vs Guoji yiyao weisheng daobao）不能放过去
                ignore = True
            if not ignore:
                stop = {"journal", "review", "letters", "proceedings", "transactions",
                        "international", "research", "studies", "bulletin"}
                wa = {w for w in norm_text(cited.journal).split() if len(w) >= 4 and w not in stop}
                wb = {w for w in norm_text(rec.journal).split() if len(w) >= 4 and w not in stop}
                if wa and wb and (wa & wb):
                    ignore = True
        if not ignore:
            mismatches.append(
                {"field": "journal", "cited": cited.journal, "found": rec.journal}
            )

    def _norm_vol(v: str) -> str:
        s = str(v).strip()
        if re.fullmatch(r"\d+", s):
            return str(int(s))
        return s.casefold()

    cv, rv = clean_biblio_field(cited.volume), clean_biblio_field(rec.volume)
    ci, ri = clean_biblio_field(cited.issue), clean_biblio_field(rec.issue)
    if cv and rv and _norm_vol(cv) != _norm_vol(rv):
        # 卷期区间被拆错：引用把 issue 范围当成了 volume
        if not (ci is None and ri and _norm_vol(cv) == _norm_vol(ri)):
            mismatches.append(
                {"field": "volume", "cited": cited.volume, "found": rec.volume}
            )

    if ci and ri and _norm_vol(ci) != _norm_vol(ri):
        mismatches.append({"field": "issue", "cited": cited.issue, "found": rec.issue})

    if cited.pages and rec.pages and not pages_compatible(cited.pages, rec.pages):
        mismatches.append(
            {"field": "pages", "cited": cited.pages, "found": rec.pages}
        )

    if cited.doi and rec.doi and norm_doi(cited.doi) != norm_doi(rec.doi):
        mismatches.append({"field": "doi", "cited": cited.doi, "found": rec.doi})

    if cited.pmid and rec.pmid and str(cited.pmid) != str(rec.pmid):
        mismatches.append({"field": "pmid", "cited": cited.pmid, "found": rec.pmid})

    return mismatches


def pick_best(cited: ParsedRef, records: list[Record]) -> Record | None:
    ranked: list[Record] = []
    key = cited.title or cited.raw
    for rec in records:
        rec.title_sim = title_similarity(key, rec.title)
        # 若已解析出题名，不再用整段书目去抬分（整段含作者刊名，容易误伤）
        if not cited.title:
            rec.title_sim = max(rec.title_sim, title_similarity(cited.raw, rec.title))
        ranked.append(rec)

    def sort_key(r: Record) -> tuple:
        low = 1 if is_low_value(r) else 0
        typ_bonus = 0
        if (r.typ or "") in {"journal-article", "proceedings-article", "book", "book-chapter", "article"}:
            typ_bonus = 1
        doi_miss = 0 if (cited.doi and r.doi and norm_doi(cited.doi) == norm_doi(r.doi)) else 1
        if cited.year and r.year:
            year_dist = abs(int(cited.year) - int(r.year))
        else:
            year_dist = 99
        return (low, -r.title_sim, doi_miss, year_dist, -typ_bonus, -r.score)

    ranked.sort(key=sort_key)
    return ranked[0] if ranked else None


def is_clearly_other_work(
    cited: ParsedRef, rec: Record, fields: set[str], *, title_is_strong: bool
) -> bool:
    """题名相近甚至相同，但书目多处对不上、且没有 DOI/PMID 锁定时，视为另一篇。

    宁可标疑似并附原文链接，也不能把编造条目放行成已验证。
    同一篇被改了一两个字段（测试集的篡改项）不得走这条。
    """
    doi_locked = bool(cited.doi and rec.doi and norm_doi(cited.doi) == norm_doi(rec.doi))
    pmid_locked = bool(cited.pmid and rec.pmid and str(cited.pmid) == str(rec.pmid))
    if doi_locked or pmid_locked:
        return False
    if not title_is_strong:
        return (
            (("authors" in fields) and ("journal" in fields or "year" in fields))
            or (
                "journal" in fields
                and "year" in fields
                and (not cited.authors or not rec.authors)
            )
            or ("title" in fields and "journal" in fields and "year" in fields)
        )
    # 题名相同或极近：短通用题名撞上同刊另一篇真实文献
    if "authors" not in fields:
        return False
    if not (cited.journal and rec.journal and journal_similar(cited.journal, rec.journal)):
        return False
    return len(fields & {"year", "volume", "pages"}) >= 2


def classify(cited: ParsedRef, checker: Checker) -> dict[str, Any]:
    notes: list[str] = []
    doi_record = None
    pmid_record = None
    candidates: list[Record] = []
    checker.hard_failures.clear()

    if cited.doi:
        doi_record = checker.crossref_doi(cited.doi)
        cr_failed = checker.last_query_failed
        if doi_record is None:
            # Crossref 没有时再试 OpenAlex（部分中文 DOI 只在 OpenAlex）
            doi_record = checker.openalex_doi(cited.doi)
            oa_failed = checker.last_query_failed
            if doi_record is None:
                if cr_failed or oa_failed:
                    notes.append(
                        f"所给 DOI（{cited.doi}）查询因网络或接口错误失败，"
                        "本次不能据此判断该 DOI 是否存在。"
                    )
                else:
                    notes.append(f"所给 DOI（{cited.doi}）在 Crossref / OpenAlex 中无法解析。")
        if doi_record:
            candidates.append(doi_record)

    if cited.pmid:
        pmid_record = checker.epmc_pmid(cited.pmid)
        if pmid_record:
            candidates.append(pmid_record)
        elif checker.last_query_failed:
            notes.append(
                f"所给 PMID（{cited.pmid}）查询因网络或接口错误失败，"
                "本次不能据此判断该 PMID 是否存在。"
            )
        else:
            notes.append(f"所给 PMID（{cited.pmid}）在 Europe PMC 中未找到对应记录。")

    # 用完整书目做 Crossref bibliographic 检索（官方推荐用法）
    # 去掉 DOI/PMID/URL，避免把「DOI 指向的另一篇」检索分抬上去
    biblio_q = bibliographic_remainder(cited.raw)
    # 仅 DOI/URL 时不要拿空查询去检索，以免返回无关记录
    if len(biblio_q) >= 8:
        candidates.extend(checker.crossref_biblio(biblio_q[:400], rows=5))
        search_q = cited.title or biblio_q
        candidates.extend(checker.openalex_search(search_q[:400], per_page=5))

    # 去重（按 DOI 或题名）
    uniq: list[Record] = []
    seen: set[str] = set()
    for rec in candidates:
        key = rec.doi or norm_text(rec.title or "") + str(rec.year or "")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(rec)
    candidates = uniq

    # DOI / PMID 是否指向另一篇文章
    doi_conflict = False
    pmid_conflict = False
    title_key = cited.title or ""
    # 弱题名（如题名中段的引号短语）不能用来判断冲突，改用书目残余
    if (is_weak_title(title_key, cited.raw) or len(norm_text(title_key)) < 8) and not is_identifier_only(cited):
        rem = bibliographic_remainder(cited.raw)
        if len(norm_text(rem)) >= 8:
            title_key = rem
        elif cited.raw:
            title_key = cited.raw

    def conflicts(rec: Record | None) -> bool:
        # 仅 DOI / 仅 URL / 仅 PMID 时，不能拿「库中题名 vs 原始 URL」判冲突
        if is_identifier_only(cited):
            return False
        if not rec or not rec.title:
            return False
        if record_supported_by_cite(cited, rec):
            return False
        if not title_key or len(norm_text(title_key)) < 8:
            return False
        return title_similarity(title_key, rec.title) < 0.75

    if doi_record and conflicts(doi_record):
        doi_conflict = True
        link = record_url(doi_record) or ""
        notes.append(
            "你提供的 DOI 是真实的，但指向另一篇文章："
            f"《{doi_record.title}》（{doi_record.year or '年份不详'}，"
            f"{doi_record.journal or '来源不详'}）。"
            f"验证链接：{link}"
        )
    if pmid_record and conflicts(pmid_record):
        pmid_conflict = True
        link = record_url(pmid_record) or ""
        notes.append(
            "你提供的 PMID 是真实的，但指向另一篇文章："
            f"《{pmid_record.title}》（{pmid_record.year or '年份不详'}，"
            f"{pmid_record.journal or '来源不详'}）。"
            f"验证链接：{link}"
        )

    # 给候选打相似度，排除低价值抢位记录（除非没有更好的）
    best = pick_best(cited, candidates)
    # 若最佳是低价值且相似度不是极高，再在非低价值里找
    if best and is_low_value(best) and best.title_sim < 0.95:
        alt = [r for r in candidates if not is_low_value(r)]
        alt_best = pick_best(cited, alt) if alt else None
        if alt_best and alt_best.title_sim >= RELATED_TITLE - 0.02:
            best = alt_best
    # DOI 能解析且题名不冲突时，优先采用 DOI 记录（避免同名旧版抢位）
    # 仅 DOI/URL、未提供题名时，直接采用该记录并视为题名已由标识符锁定
    if doi_record and record_supported_by_cite(cited, doi_record):
        doi_conflict = False
        best = doi_record
        doi_record.title_sim = max(getattr(doi_record, "title_sim", 0.0) or 0.0, 1.0)
    elif doi_record and not doi_conflict:
        if is_identifier_only(cited):
            best = doi_record
            doi_record.title_sim = 1.0
        else:
            key = cited.title or bibliographic_remainder(cited.raw)
            doi_record.title_sim = title_similarity(key, doi_record.title)
            if doi_record.title_sim >= STRONG_TITLE:
                best = doi_record
    if pmid_record and record_supported_by_cite(cited, pmid_record):
        pmid_conflict = False
        if best is None or is_identifier_only(cited) or record_supported_by_cite(cited, pmid_record):
            if best is not doi_record or is_identifier_only(cited):
                best = pmid_record
                pmid_record.title_sim = max(getattr(pmid_record, "title_sim", 0.0) or 0.0, 1.0)
    elif pmid_record and not pmid_conflict and is_identifier_only(cited):
        if best is None or best is pmid_record:
            best = pmid_record
            pmid_record.title_sim = 1.0

    match = None
    mismatches: list[dict[str, Any]] = []
    status = "not_found"
    related_other = None

    if best and best.title_sim >= STRONG_TITLE:
        match = best
        mismatches = compare_fields(cited, best)
        if doi_conflict:
            # 文章能对上，但用户给的 DOI 是别人的
            if not any(m["field"] == "doi" for m in mismatches):
                mismatches.append(
                    {
                        "field": "doi",
                        "cited": cited.doi,
                        "found": best.doi or "（库中记录的 DOI 与引用不一致）",
                    }
                )
        if pmid_conflict:
            if not any(m["field"] == "pmid" for m in mismatches):
                mismatches.append(
                    {
                        "field": "pmid",
                        "cited": cited.pmid,
                        "found": best.pmid or "（库中记录的 PMID 与引用不一致）",
                    }
                )
        strong_fields = {m["field"] for m in mismatches}
        if is_clearly_other_work(cited, best, strong_fields, title_is_strong=True):
            related_other = best
            match = None
            mismatches = []
            if checker.hard_failures:
                status = "error"
                notes.append(
                    "因网络或接口请求失败（超时、无法连接或 HTTP 429 等），"
                    "本次核查失败，无法下结论。"
                    "这与「各库都正常返回但没有匹配」不同，不能写成「查无此文」。"
                )
            elif doi_conflict or pmid_conflict:
                status = "suspected_fabricated"
                notes.append(
                    "题名与库中一篇记录相同或极近，但作者、年份或页码对不上，"
                    "且所给 DOI 或 PMID 指向的是另一篇文献。请核对该记录原文。"
                    f"相近记录：{record_url(related_other) or ''}"
                )
            elif looks_complete(cited) and cited.language_hint != "zh":
                status = "suspected_fabricated"
                notes.append(
                    "题名与库中一篇记录相同或极近，但作者和年份/卷期/页码均不符，"
                    "更像是同刊或同题的另一篇，不能视为同一篇。"
                    "条目看起来信息完整，因此标为「疑似编造」。请核对该记录原文："
                    f"{record_url(related_other) or ''}。"
                    "这不等于最终宣判。"
                )
            else:
                status = "not_found"
                notes.append(
                    "题名与库中一篇记录相同或极近，但作者和年份/卷期/页码均不符，"
                    "不能视为同一篇。请核对该记录原文："
                    f"{record_url(related_other) or ''}。"
                    "未找到并不等于一定是假的。"
                )
        else:
            status = "verified" if not mismatches else "field_mismatch"
    elif best and best.title_sim >= RELATED_TITLE:
        # 题名只是相近、作者和期刊也对不上时，不宜当成「同一篇的字段不符」
        tmp = compare_fields(cited, best)
        fields = {m["field"] for m in tmp}
        clearly_other = is_clearly_other_work(cited, best, fields, title_is_strong=False)
        if clearly_other:
            best_nearby = best
            best = None
            # 落到下面「没找到足够像的题名」分支，但保留相近记录供参考
            # 先记下 nearby 所需信息
            # 用一个哨兵：后面 else 再处理 nearby
            # 这里直接走与「无足够相似题名」相同的判定
            if checker.hard_failures:
                status = "error"
                notes.append(
                    "因网络或接口请求失败（超时、无法连接或 HTTP 429 等），"
                    "本次核查失败，无法下结论。"
                    "这与「各库都正常返回但没有匹配」不同，不能写成「查无此文」。"
                )
            elif doi_conflict or pmid_conflict:
                status = "suspected_fabricated"
                notes.append(
                    "按题名未在 Crossref / OpenAlex 中找到对应文章，"
                    "且所给 DOI 或 PMID 指向的是另一篇完全不同的文献。"
                )
            elif looks_complete(cited) and cited.language_hint != "zh":
                status = "suspected_fabricated"
                notes.append(
                    "数据库中只有题名相近、但作者和来源都不符的记录，不能视为同一篇。"
                    "条目看起来信息完整，因此标为「疑似编造」。"
                    "这不等于最终宣判：新刊、书籍、预印本、未收录会议论文也可能查不到。"
                )
            else:
                status = "not_found"
                notes.append(
                    "数据库中只有题名相近、但并非同一篇的记录。"
                    "未找到并不等于一定是假的。"
                )
            # 把相近记录放到 nearby（在 result 组装处会读 best；这里 match 保持空）
            match = None
            mismatches = []
            # 暂存
            related_other = best_nearby
        else:
            match = best
            mismatches = tmp
            if not any(m["field"] == "title" for m in mismatches):
                mismatches.insert(
                    0,
                    {
                        "field": "title",
                        "cited": cited.title or cited.raw[:180],
                        "found": best.title,
                        "similarity": round(best.title_sim, 3),
                        "note": "题名相近，但不能视为同一篇",
                    }
                )
            status = "field_mismatch"
            notes.append(
                "数据库中存在题名相近的记录，但并非完全同一篇。"
                "下面列出的是相近记录，不是替你编造的「正确参考文献」。"
            )
    else:
        # 没找到足够像的题名。先看请求是否失败，避免先写「因此标为疑似编造」再改口。
        if checker.hard_failures:
            status = "error"
            notes.append(
                "因网络或接口请求失败（超时、无法连接或 HTTP 429 等），"
                "本次核查失败，无法下结论。"
                "这与「各库都正常返回但没有匹配」不同，不能写成「查无此文」。"
            )
        elif doi_conflict or pmid_conflict:
            status = "suspected_fabricated"
            notes.append(
                "按题名未在 Crossref / OpenAlex 中找到对应文章，"
                "且所给 DOI 或 PMID 指向的是另一篇完全不同的文献。"
            )
        elif looks_complete(cited) and cited.language_hint != "zh":
            status = "suspected_fabricated"
            notes.append(
                "在 Crossref、OpenAlex"
                + ("、Europe PMC" if cited.pmid else "")
                + "中都没有找到足够相似的记录。"
                "条目看起来信息完整，因此标为「疑似编造」。"
                "这不等于最终宣判：新刊、书籍、预印本、未收录会议论文也可能查不到。"
            )
        else:
            status = "not_found"
            if cited.language_hint == "zh":
                notes.append(
                    "在 Crossref / OpenAlex 中未找到足够相似的记录。"
                    "这两个库对中文期刊、学位论文、书籍的覆盖明显不足，"
                    "「查无此文」不能等同于「一定是假的」，也不能据此确认是假的。"
                    "请再查学校图书馆或 Google Scholar。"
                    "本工具不支持需授权的中文商业文献库（不支持知网、万方）。"
                )
            else:
                notes.append(
                    "在公开库中未找到足够相似的记录。"
                    "未找到并不等于一定是假的，尤其是书籍、学位论文、新刊和未收录的会议论文。"
                )

    # 强证据兜底：DOI 或 PMID 直查已能对上同一篇时，不得判疑似编造或查无此文
    strong_id = None
    if doi_record and record_supported_by_cite(cited, doi_record):
        strong_id = doi_record
    elif pmid_record and record_supported_by_cite(cited, pmid_record):
        strong_id = pmid_record
    if strong_id is not None and status in {"suspected_fabricated", "not_found"}:
        match = strong_id
        mismatches = compare_fields(cited, strong_id)
        status = "verified" if not mismatches else "field_mismatch"
        notes.append(
            "所给 DOI 或 PMID 已指向这篇文献，按同一篇核对字段，"
            "不以「疑似编造」或「查无此文」下结论。"
            f"验证链接：{record_url(strong_id) or ''}"
        )

    result = {
        "raw": cited.raw,
        "parsed": {
            "authors": cited.authors,
            "year": cited.year,
            "title": cited.title,
            "journal": cited.journal,
            "volume": cited.volume,
            "issue": cited.issue,
            "pages": cited.pages,
            "doi": cited.doi,
            "pmid": cited.pmid,
            "language_hint": cited.language_hint,
        },
        "status": status,
        "status_zh": STATUS_ZH[status],
        "mismatched_fields": mismatches,
        "notes": notes,
        "match": match.to_public() if match else None,
        "verify_url": record_url(match) if match else None,
        "doi_record": doi_record.to_public() if doi_record else None,
        "pmid_record": pmid_record.to_public() if pmid_record else None,
    }
    # 硬规则：查不到时不编造替代条目。相近记录必须带说明。
    if status in {"not_found", "suspected_fabricated"}:
        result["match"] = None
        result["verify_url"] = None
        hint = related_other or best
        result["nearby"] = (
            {
                "title": hint.title,
                "year": hint.year,
                "journal": hint.journal,
                "doi": hint.doi,
                "url": record_url(hint),
                "title_sim": round(hint.title_sim, 3),
                "note": "仅供参考的相近记录，不是替你生成的正确引用。",
            }
            if hint and hint.title_sim >= 0.55
            else None
        )
    return result


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

STATUS_COLOR = {
    "verified": "#1b7f3a",
    "field_mismatch": "#b26a00",
    "not_found": "#b42318",
    "suspected_fabricated": "#8b1111",
    "error": "#555555",
}
STATUS_BG = {
    "verified": "#e8f7ee",
    "field_mismatch": "#fff6e0",
    "not_found": "#fdecea",
    "suspected_fabricated": "#f9e2e2",
    "error": "#f0f0f0",
}
STATUS_MARK = {
    "verified": "✓",
    "field_mismatch": "△",
    "not_found": "×",
    "suspected_fabricated": "×",
    "error": "!",
}


def render_markdown(results: list[dict[str, Any]]) -> str:
    counts = {k: 0 for k in STATUS_ZH}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [
        "# 参考文献核查报告",
        "",
        f"共 {len(results)} 条："
        + "，".join(f"{STATUS_ZH[k]} {v}" for k, v in counts.items() if v),
        "",
        "> 查不到时不会编造替代条目。「查无此文」或「疑似编造」都不等于最终宣判。中文期刊覆盖有限，不支持知网、万方，不能确认中文条目是否为假。会把题名或 DOI 发给 Crossref / OpenAlex / Europe PMC，不上传全文。",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"## {i}. {r['status_zh']}")
        lines.append("")
        lines.append(f"> {r['raw']}")
        lines.append("")
        if r.get("mismatched_fields"):
            lines.append("不符字段：")
            for m in r["mismatched_fields"]:
                name = FIELD_ZH.get(m["field"], m["field"])
                extra = f"（相似度 {m['similarity']}）" if "similarity" in m else ""
                note = f"；{m['note']}" if m.get("note") else ""
                lines.append(f"- **{name}**{extra}{note}：引用为「{m.get('cited')}」，库中为「{m.get('found')}」")
            lines.append("")
        if r.get("match") and r["status"] in {"verified", "field_mismatch"}:
            m = r["match"]
            lines.append("数据库中的对应/相近记录（不是替你编造的新条目）：")
            lines.append(
                f"- {m.get('title')}（{m.get('year')}，{m.get('journal') or ''}）"
            )
            if r.get("verify_url"):
                lines.append(f"- 验证链接：{r['verify_url']}")
            lines.append("")
        for n in r.get("notes") or []:
            lines.append(f"- {n}")
        if r.get("nearby"):
            nb = r["nearby"]
            lines.append(
                f"- 相近记录（仅供参考，相似度 {nb.get('title_sim')}）："
                f"《{nb.get('title')}》 {nb.get('url') or ''}"
            )
        lines.append("")
    return "\n".join(lines)


def render_html(results: list[dict[str, Any]], title: str = "参考文献核查报告") -> str:
    counts = {k: 0 for k in STATUS_ZH}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary_bits = []
    for k, lab in STATUS_ZH.items():
        if counts.get(k):
            summary_bits.append(
                f'<span class="pill {k}">{html.escape(lab)} {counts[k]}</span>'
            )
    cards = []
    for i, r in enumerate(results, 1):
        st = r["status"]
        mism = ""
        if r.get("mismatched_fields"):
            rows = []
            for m in r["mismatched_fields"]:
                name = FIELD_ZH.get(m["field"], m["field"])
                note = f'<div class="tiny">{html.escape(str(m.get("note", "")))}</div>' if m.get("note") or m.get("similarity") is not None else ""
                if m.get("similarity") is not None:
                    note = f'<div class="tiny">相似度 {m["similarity"]}' + (f'；{html.escape(m["note"])}' if m.get("note") else "") + "</div>"
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(name)}</td>"
                    f"<td>{html.escape(str(m.get('cited', '')))}</td>"
                    f"<td>{html.escape(str(m.get('found', '')))}</td>"
                    f"<td class='bad'>不符{note}</td>"
                    "</tr>"
                )
            mism = (
                "<table class='cmp'><thead><tr><th>字段</th><th>你提供的</th>"
                "<th>数据库中的记录</th><th></th></tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table>"
            )
        match_html = ""
        if r.get("match") and st in {"verified", "field_mismatch"}:
            m = r["match"]
            url = r.get("verify_url") or ""
            link = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(url)}</a>' if url else ""
            match_html = (
                "<div class='found'>"
                "<div class='label'>数据库中的对应/相近记录（不是替你编造的新条目）</div>"
                f"<div>《{html.escape(m.get('title') or '')}》"
                f"（{html.escape(str(m.get('year') or ''))}，{html.escape(m.get('journal') or '')}）</div>"
                f"<div>{link}</div></div>"
            )
        notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in (r.get("notes") or []))
        nearby = ""
        if r.get("nearby"):
            nb = r["nearby"]
            url = nb.get("url") or ""
            nearby = (
                f"<div class='nearby'>相近记录仅供参考（相似度 {nb.get('title_sim')}），"
                "不是替你生成的正确引用："
                f"《{html.escape(nb.get('title') or '')}》"
                + (f' <a href="{html.escape(url)}" target="_blank" rel="noopener">打开</a>' if url else "")
                + "</div>"
            )
        cards.append(
            f"<article class='card {html.escape(st)}' id='ref-{i}'>"
            f"<header><span class='mark'>{STATUS_MARK[st]}</span>"
            f"<span class='idx'>第 {i} 条</span>"
            f"<span class='status'>{html.escape(r['status_zh'])}</span></header>"
            f"<p class='raw'>{html.escape(r['raw'])}</p>"
            f"{mism}{match_html}"
            f"{('<ul class=\"notes\">'+notes_html+'</ul>') if notes_html else ''}"
            f"{nearby}"
            "</article>"
        )
    css = """
    :root { --fg:#1a1a1a; --muted:#5c5c5c; --line:#e6e2d8; }
    * { box-sizing: border-box; }
    body { margin:0; font: 16px/1.55 "Noto Sans CJK SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
           color:var(--fg); background:#f7f4ee; }
    main { max-width: 920px; margin: 0 auto; padding: 32px 20px 64px; }
    h1 { font-size: 1.6rem; margin: 0 0 8px; }
    .lead { color: var(--muted); margin-bottom: 20px; }
    .pills { display:flex; flex-wrap:wrap; gap:8px; margin: 12px 0 24px; }
    .pill { border-radius:999px; padding:4px 12px; font-size:14px; }
    .pill.verified { background:#e8f7ee; color:#1b7f3a; }
    .pill.field_mismatch { background:#fff6e0; color:#8a5a00; }
    .pill.not_found, .pill.suspected_fabricated { background:#fdecea; color:#8b1111; }
    .pill.error { background:#eef0f6; color:#2c3a6b; }
    .card { background:#fff; border:1px solid var(--line); border-radius:14px;
            padding:16px 18px; margin: 0 0 14px; border-left: 6px solid #ccc; }
    .card.verified { border-left-color:#1b7f3a; }
    .card.field_mismatch { border-left-color:#d89000; }
    .card.not_found, .card.suspected_fabricated { border-left-color:#c42b1c; }
    .card.error { border-left-color:#4a5c8c; }
    header { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
    .mark { font-weight:700; font-size:1.2rem; }
    .card.verified .mark, .card.verified .status { color:#1b7f3a; }
    .card.field_mismatch .mark, .card.field_mismatch .status { color:#8a5a00; }
    .card.not_found .mark, .card.not_found .status,
    .card.suspected_fabricated .mark, .card.suspected_fabricated .status { color:#8b1111; }
    .idx { color:var(--muted); font-size:13px; }
    .status { font-weight:700; }
    .raw { background:#faf8f3; padding:10px 12px; border-radius:8px; }
    table.cmp { width:100%; border-collapse:collapse; margin:10px 0; font-size:14px; }
    table.cmp th, table.cmp td { border:1px solid var(--line); padding:6px 8px; vertical-align:top; }
    table.cmp th { background:#faf8f3; text-align:left; }
    .bad { color:#8b1111; white-space:nowrap; }
    .tiny { color:var(--muted); font-weight:400; font-size:12px; }
    .found { background:#e8f7ee; padding:10px 12px; border-radius:8px; margin:8px 0; }
    .found .label { font-size:12px; color:#1b7f3a; margin-bottom:4px; }
    .notes { color:#3a3a3a; }
    .nearby { font-size:14px; color:var(--muted); }
    a { color:#0b57d0; }
    footer { color:var(--muted); font-size:13px; margin-top:24px; }
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{css}</style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <p class="lead">共 {len(results)} 条。查不到时不会编造替代条目。
  「查无此文」或「疑似编造」都不等于最终宣判。中文期刊覆盖有限，不支持知网、万方，不能确认中文条目是否为假。
  本次查询把题名或 DOI 发送给了 Crossref、OpenAlex、Europe PMC，没有上传全文。</p>
  <div class="pills">{''.join(summary_bits)}</div>
  {''.join(cards)}
  <footer>本报告对照 Crossref、OpenAlex、Europe PMC 生成。查询时会把题名或 DOI 发给这些公开学术数据库，不上传全文。核查时间以你运行脚本时为准。</footer>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_text(text: str, mailto: str | None = None, delay: float = 0.4, progress=None) -> list[dict[str, Any]]:
    blocks = split_references(text)
    checker = Checker(mailto=mailto, delay=delay)
    results = []
    total = len(blocks)
    for i, raw in enumerate(blocks, 1):
        if progress:
            progress(i, total, raw)
        parsed = parse_one(raw)
        results.append(classify(parsed, checker))
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="核查参考文献是否真实存在（Crossref / OpenAlex / Europe PMC）。"
    )
    p.add_argument("input", nargs="?", help="包含参考文献列表的文本文件；省略则读标准输入")
    p.add_argument("-o", "--html", help="写出 HTML 报告路径")
    p.add_argument("--md", help="写出 Markdown 报告路径")
    p.add_argument("--json", help="写出 JSON 结果路径")
    p.add_argument("--mailto", help="用于公开接口礼貌标识的邮箱（推荐填写，可提高 Crossref 限额）")
    p.add_argument("--delay", type=float, default=0.4, help="两次请求之间的间隔秒数，默认 0.4")
    args = p.parse_args(argv)

    if args.input:
        path = Path(args.input)
        if not path.is_file():
            print(
                f"找不到输入文件：{args.input}。请确认路径是否写对。",
                file=sys.stderr,
            )
            return 2
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"无法读取输入文件：{args.input}（{e}）。", file=sys.stderr)
            return 2
    else:
        if sys.stdin.isatty():
            print("请把参考文献列表粘贴进来，然后按 Ctrl-D（Windows 为 Ctrl-Z）结束：", file=sys.stderr)
        text = sys.stdin.read()
    if not text.strip():
        print("没有读到参考文献。", file=sys.stderr)
        return 2

    def progress(i, total, raw):
        preview = re.sub(r"\s+", " ", raw)[:60]
        print(f"正在核查 {i}/{total}：{preview}…", file=sys.stderr)

    results = run_text(text, mailto=args.mailto, delay=args.delay, progress=progress)

    # 默认打印 Markdown，并在未指定 -o 时，于输入文件旁写一份 HTML
    md = render_markdown(results)
    html_doc = render_html(results)
    payload = json.dumps(results, ensure_ascii=False, indent=2)

    html_path = args.html
    if not html_path and args.input:
        html_path = str(Path(args.input).with_suffix("")) + "_report.html"
    if html_path:
        Path(html_path).write_text(html_doc, encoding="utf-8")
        print(f"已写出 HTML 报告：{html_path}", file=sys.stderr)
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        print(f"已写出 Markdown 报告：{args.md}", file=sys.stderr)
    if args.json:
        Path(args.json).write_text(payload, encoding="utf-8")
        print(f"已写出 JSON：{args.json}", file=sys.stderr)

    sys.stdout.write(md)
    if not md.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

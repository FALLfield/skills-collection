#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立构造 100 条测试集（不调用 check_refs.py，不根据工具输出写 gold）。

用法：
  python3 tests/hundred/build_batch.py          # 默认 batch1，种子 20261111
  python3 tests/hundred/build_batch.py --batch 2 --seed 20261111-b2 --outdir tests/hundred_b2

步骤：
  1. 按学科从 Crossref / OpenAlex 拉取期刊论文，把原始 JSON 冻在 raw/ 下。
  2. 用固定种子从合格池里抽样，格式化真实条目与篡改条目。
  3. 从 Walters & Wilder (2023) 附录及若干公开案例中选取编造/幻觉条目。
  4. 写出 input.txt 与 gold.json。gold 只依据「这条是怎么造出来的」和库中原始记录。
"""

from __future__ import annotations

import argparse
import html
import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "RefCheck/1.0 (hundred-set constructor; mailto:refcheck@localhost)"
DELAY = 0.4
MACAU = timezone(timedelta(hours=8), name="Asia/Macau")

LOW_TITLE_PREFIXES = (
    "faculty opinions recommendation of",
    "review for ",
    "author correction:",
    "publisher correction:",
    "erratum:",
    "retraction:",
    "retracted:",
    "expression of concern",
    "correction to:",
)
LOW_TYPES = {"dataset", "peer-review", "component", "grant", "journal-issue"}


def now_label() -> str:
    return datetime.now(MACAU).strftime("%Y-%m-%d %H:%M:%S") + " Asia/Macau（UTC+8）"


def http_get_json(url: str, timeout: int = 40) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def polite(last: list[float]) -> None:
    dt = time.time() - last[0]
    if dt < DELAY:
        time.sleep(DELAY - dt)
    last[0] = time.time()


def year_of(obj) -> int | None:
    if not obj:
        return None
    parts = obj.get("date-parts") if isinstance(obj, dict) else None
    if parts and parts[0] and str(parts[0][0]).isdigit():
        y = int(parts[0][0])
        if 1900 <= y <= 2026:
            return y
    return None


def norm_doi(d: str | None) -> str | None:
    if not d:
        return None
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d.strip(), flags=re.I)
    d = d.replace("doi:", "").strip().rstrip(").,;")
    return d.lower() or None


def is_cjk(s: str) -> bool:
    return len(re.findall(r"[\u4e00-\u9fff]", s or "")) >= 4


def clean_txt(s: str | None) -> str:
    s = html.unescape((s or "").replace(" ", " "))
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def clean_biblio_field(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or re.fullmatch(r"(?i)null|none|n/?a|na|undefined|nil", s):
        return None
    return s


def complete_crossref(item: dict) -> dict | None:
    typ = (item.get("type") or "").lower()
    if typ in LOW_TYPES:
        return None
    title = clean_txt((item.get("title") or [""])[0] or "")
    if not title or len(title) < 20:
        return None
    tl = title.lower()
    if any(tl.startswith(p) for p in LOW_TITLE_PREFIXES):
        return None
    journal = clean_txt((item.get("container-title") or [""])[0] or "")
    if not journal:
        return None
    year = year_of(item.get("published-print")) or year_of(item.get("published")) or year_of(item.get("issued"))
    if not year:
        return None
    doi = norm_doi(item.get("DOI"))
    if not doi:
        return None
    authors = []
    for a in item.get("author") or []:
        fam = clean_txt(a.get("family") or "")
        giv = clean_txt(a.get("given") or "")
        if fam.count(" ") >= 2:
            continue  # 库中把多名作者挤进 family 字段的脏记录丢掉
        if (fam.count("，") + fam.count("、") + fam.count(",")) >= 1 and len(re.findall(r"[\u4e00-\u9fff]", fam)) >= 4:
            continue
        if len(re.findall(r"[\u4e00-\u9fff]", fam)) >= 5:
            continue
        if fam:
            authors.append({"family": fam, "given": giv})
    if len(authors) < 1:
        return None
    return {
        "source": "crossref",
        "doi": doi,
        "title": title,
        "journal": journal,
        "year": year,
        "volume": clean_biblio_field(item.get("volume")),
        "issue": clean_biblio_field(item.get("issue")),
        "pages": clean_biblio_field(item.get("page")),
        "type": typ or "journal-article",
        "authors": authors,
        "url": f"https://doi.org/{doi}",
    }


def complete_openalex(item: dict) -> dict | None:
    title = clean_txt(item.get("title") or item.get("display_name") or "")
    if not title or len(title) < 8:
        return None
    loc = item.get("primary_location") or {}
    src = loc.get("source") or {}
    journal = clean_txt(src.get("display_name") or "")
    year = item.get("publication_year")
    doi = norm_doi(item.get("doi") or "")
    biblio = item.get("biblio") or {}
    authors = []
    for a in item.get("authorships") or []:
        name = ((a.get("author") or {}).get("display_name") or "").strip()
        if not name:
            continue
        # OpenAlex display: usually Given Family
        parts = name.split()
        if len(parts) >= 2 and not re.search(r"[\u4e00-\u9fff]", name):
            authors.append({"family": parts[-1], "given": " ".join(parts[:-1])})
        else:
            authors.append({"family": name, "given": ""})
    if not year or not authors:
        return None
    first, last = biblio.get("first_page"), biblio.get("last_page")
    pages = f"{first}-{last}" if first and last else (str(first) if first else None)
    pmid = None
    ids = item.get("ids") or {}
    if ids.get("pmid"):
        m = re.search(r"(\d+)$", str(ids["pmid"]))
        if m:
            pmid = m.group(1)
    return {
        "source": "openalex",
        "doi": doi,
        "pmid": pmid,
        "title": title,
        "journal": journal or None,
        "year": int(year),
        "volume": clean_biblio_field(biblio.get("volume")),
        "issue": clean_biblio_field(biblio.get("issue")),
        "pages": pages,
        "type": item.get("type") or "article",
        "authors": authors,
        "url": loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else item.get("id")),
        "openalex_id": item.get("id"),
    }


FIELD_QUERIES = [
    # medicine
    {"field": "medicine", "api": "crossref", "params": {"query": "randomized controlled trial cardiovascular outcome", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2024", "rows": 25}},
    {"field": "medicine", "api": "crossref", "params": {"query": "cancer immunotherapy checkpoint", "filter": "type:journal-article,from-pub-date:2017,until-pub-date:2024", "rows": 20}},
    {"field": "medicine", "api": "crossref", "params": {"query.container-title": "The Lancet", "query": "stroke trial", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 15}},
    {"field": "medicine", "api": "crossref", "params": {"query": "major depressive disorder antidepressant", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 15}},
    # cs
    {"field": "cs", "api": "crossref", "params": {"query": "convolutional neural network image classification", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 20}},
    {"field": "cs", "api": "crossref", "params": {"query": "distributed systems consensus replication", "filter": "type:journal-article,from-pub-date:2014,until-pub-date:2023", "rows": 15}},
    {"field": "cs", "api": "crossref", "params": {"query": "natural language processing pretrained language model", "filter": "type:journal-article,from-pub-date:2019,until-pub-date:2024", "rows": 20}},
    {"field": "cs", "api": "crossref", "params": {"query": "computer security side channel", "filter": "type:journal-article,from-pub-date:2015,until-pub-date:2023", "rows": 15}},
    # physics
    {"field": "physics", "api": "crossref", "params": {"query": "gravitational wave detection ligo", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 15}},
    {"field": "physics", "api": "crossref", "params": {"query": "quantum entanglement photon experiment", "filter": "type:journal-article,from-pub-date:2015,until-pub-date:2023", "rows": 15}},
    {"field": "physics", "api": "crossref", "params": {"query": "topological insulator electronic transport", "filter": "type:journal-article,from-pub-date:2014,until-pub-date:2022", "rows": 15}},
    {"field": "physics", "api": "crossref", "params": {"query": "exoplanet transit atmosphere", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 15}},
    # biology
    {"field": "biology", "api": "crossref", "params": {"query": "CRISPR Cas9 genome editing mammalian", "filter": "type:journal-article,from-pub-date:2014,until-pub-date:2023", "rows": 15}},
    {"field": "biology", "api": "crossref", "params": {"query": "gut microbiome diversity human", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 15}},
    {"field": "biology", "api": "crossref", "params": {"query": "single-cell RNA sequencing atlas", "filter": "type:journal-article,from-pub-date:2017,until-pub-date:2023", "rows": 15}},
    {"field": "biology", "api": "crossref", "params": {"query": "photosynthesis protein structure", "filter": "type:journal-article,from-pub-date:2015,until-pub-date:2023", "rows": 15}},
    # social
    {"field": "social", "api": "crossref", "params": {"query": "income inequality social mobility", "filter": "type:journal-article,from-pub-date:2015,until-pub-date:2023", "rows": 15}},
    {"field": "social", "api": "crossref", "params": {"query": "political polarization social media", "filter": "type:journal-article,from-pub-date:2016,until-pub-date:2023", "rows": 15}},
    {"field": "social", "api": "crossref", "params": {"query": "self-control delay of gratification", "filter": "type:journal-article,from-pub-date:2014,until-pub-date:2022", "rows": 15}},
    {"field": "social", "api": "crossref", "params": {"query.container-title": "American Economic Review", "query": "labor market", "filter": "type:journal-article,from-pub-date:2015,until-pub-date:2023", "rows": 12}},
    # Chinese (Crossref + OpenAlex)
    {"field": "chinese", "api": "crossref", "params": {"query": "高血压 流行病学", "filter": "type:journal-article,from-pub-date:2012,until-pub-date:2024", "rows": 20}},
    {"field": "chinese", "api": "crossref", "params": {"query": "冠状动脉 介入治疗", "filter": "type:journal-article,from-pub-date:2012,until-pub-date:2024", "rows": 15}},
    {"field": "chinese", "api": "openalex", "params": {"search": "糖尿病 治疗 随机对照", "per-page": 20, "mailto": "refcheck@localhost"}},
    {"field": "chinese", "api": "openalex", "params": {"search": "中医药 临床 疗效", "per-page": 15, "mailto": "refcheck@localhost"}},
]


def fetch_all(raw_dir: Path, log: dict, batch: int = 1) -> list[dict]:
    last = [0.0]
    records: list[dict] = []
    seen: set[str] = set()
    queries_log = []
    cr_dir = raw_dir / "crossref"
    oa_dir = raw_dir / "openalex"
    cr_dir.mkdir(parents=True, exist_ok=True)
    oa_dir.mkdir(parents=True, exist_ok=True)

    for q in FIELD_QUERIES:
        field, api, params = q["field"], q["api"], q["params"]
        params = dict(params)
        if batch >= 2:
            if api == "crossref":
                params["offset"] = int(params.get("offset") or 0) + 28 * (batch - 1)
            else:
                params["page"] = batch
        if api == "crossref":
            url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        else:
            url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        entry = {"field": field, "api": api, "url": url, "when": now_label(), "ok": False, "n_items": 0, "n_kept": 0}
        try:
            polite(last)
            data = http_get_json(url)
            entry["ok"] = True
            if api == "crossref":
                items = (data.get("message") or {}).get("items") or []
                entry["total_results"] = (data.get("message") or {}).get("total-results")
            else:
                items = data.get("results") or []
                entry["total_results"] = data.get("meta", {}).get("count")
            entry["n_items"] = len(items)
            kept = 0
            for it in items:
                rec = complete_crossref(it) if api == "crossref" else complete_openalex(it)
                if not rec:
                    continue
                rec["field"] = field
                rec["query_url"] = url
                key = rec.get("doi") or (rec.get("title") + str(rec.get("year")))
                if key in seen:
                    continue
                # Chinese field: prefer CJK titles; other fields: prefer non-CJK
                title = rec["title"]
                if field == "chinese" and not is_cjk(title):
                    # still keep if journal/title mixed, but skip clearly English-only
                    if not is_cjk(rec.get("journal") or ""):
                        continue
                if field != "chinese" and is_cjk(title):
                    continue
                seen.add(key)
                safe = re.sub(r"[^A-Za-z0-9._-]+", "_", (rec.get("doi") or key))[:120]
                dest = (cr_dir if api == "crossref" else oa_dir) / f"{field}_{safe}.json"
                dest.write_text(json.dumps({"query": url, "record": rec, "raw": it}, ensure_ascii=False, indent=2), encoding="utf-8")
                rec["raw_path"] = str(dest.relative_to(raw_dir.parent))
                records.append(rec)
                kept += 1
            entry["n_kept"] = kept
            print(f"  {api:8} {field:10} items={entry['n_items']} kept={kept} total={entry.get('total_results')}")
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
            print(f"  FAIL {api} {field}: {e}")
        queries_log.append(entry)
    log["queries"] = queries_log
    log["n_pool"] = len(records)
    return records


def initials(given: str) -> str:
    if not given:
        return ""
    parts = re.split(r"[\s\-]+", given)
    out = []
    for p in parts:
        p = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ\u4e00-\u9fff]", "", p)
        if not p:
            continue
        if re.search(r"[\u4e00-\u9fff]", p):
            out.append(p)
        else:
            out.append(p[0].upper() + ".")
    return " ".join(out)


def format_apa(rec: dict) -> str:
    bits = []
    for i, a in enumerate(rec["authors"]):
        fam, giv = a["family"], a.get("given") or ""
        if re.search(r"[\u4e00-\u9fff]", fam + giv):
            bits.append(fam + giv)
        else:
            ini = initials(giv)
            bits.append(f"{fam}, {ini}".strip().rstrip(","))
    if len(bits) == 1:
        author = bits[0]
    elif len(bits) == 2:
        author = f"{bits[0]}, & {bits[1]}"
    else:
        author = ", ".join(bits[:-1]) + ", & " + bits[-1]
    title = rec["title"].rstrip(".")
    year = rec["year"]
    journal = rec["journal"] or ""
    vol = rec.get("volume") or ""
    issue = rec.get("issue") or ""
    pages = rec.get("pages") or ""
    mid = journal
    if vol:
        mid += f", {vol}"
        if issue:
            mid += f"({issue})"
    if pages:
        mid += f", {pages}"
    s = f"{author} ({year}). {title}. {mid}."
    if rec.get("doi"):
        s += f" https://doi.org/{rec['doi']}"
    return s


def format_vancouver(rec: dict) -> str:
    bits = []
    for a in rec["authors"][:6]:
        fam, giv = a["family"], a.get("given") or ""
        if re.search(r"[\u4e00-\u9fff]", fam + giv):
            bits.append(fam + giv)
        else:
            ini = "".join(p[0].upper() for p in re.split(r"[\s\-]+", giv) if p and p[0].isalpha())
            bits.append(f"{fam} {ini}".strip())
    if len(rec["authors"]) > 6:
        bits.append("et al")
    author = ", ".join(bits)
    title = rec["title"].rstrip(".")
    journal = rec["journal"] or ""
    year = rec["year"]
    tail = f"{year}"
    if rec.get("volume"):
        tail += f";{rec['volume']}"
        if rec.get("issue"):
            tail += f"({rec['issue']})"
    if rec.get("pages"):
        tail += f":{rec['pages']}"
    s = f"{author}. {title}. {journal}. {tail}."
    if rec.get("doi"):
        s += f" doi: {rec['doi']}"
    return s


def format_gbt(rec: dict) -> str:
    bits = []
    for a in rec["authors"][:3]:
        fam, giv = a["family"], a.get("given") or ""
        if re.search(r"[\u4e00-\u9fff]", fam + giv):
            bits.append(fam + giv)
        else:
            ini = initials(giv).replace(".", "").replace(" ", "")
            bits.append(f"{fam} {ini}".strip() if ini else fam)
    if len(rec["authors"]) > 3:
        bits.append("等")
    author = ", ".join(bits)
    title = rec["title"].rstrip(".")
    journal = rec["journal"] or ""
    year = rec["year"]
    s = f"{author}. {title}[J]. {journal}, {year}"
    if rec.get("volume"):
        s += f", {rec['volume']}"
        if rec.get("issue"):
            s += f"({rec['issue']})"
    if rec.get("pages"):
        s += f": {rec['pages']}"
    s += "."
    if rec.get("doi"):
        s += f" DOI: {rec['doi']}"
    return s


def format_doi_only(rec: dict) -> str:
    return f"https://doi.org/{rec['doi']}"


def format_title_only(rec: dict) -> str:
    return rec["title"]


def format_pmid_only(rec: dict) -> str:
    return f"PMID: {rec['pmid']}"


def format_mla(rec: dict) -> str:
    authors = rec["authors"]
    bits = []
    for a in authors[:2]:
        fam, giv = a["family"], a.get("given") or ""
        if re.search(r"[\u4e00-\u9fff]", fam + giv):
            bits.append(fam + giv)
        else:
            bits.append(f"{fam}, {giv}".strip().rstrip(",") if giv else fam)
    if len(authors) == 1:
        author = bits[0]
    elif len(authors) == 2:
        author = f"{bits[0]}, and {bits[1]}"
    else:
        author = bits[0] + ", et al"
    title = rec["title"].rstrip(".")
    journal = rec["journal"] or ""
    parts = [f'{author}. "{title}." {journal}']
    if rec.get("volume"):
        parts.append(f"vol. {rec['volume']}")
    if rec.get("issue"):
        parts.append(f"no. {rec['issue']}")
    parts.append(str(rec["year"]))
    if rec.get("pages"):
        pg = rec["pages"]
        parts.append(("pp. " if "-" in str(pg) else "p. ") + str(pg))
    s = ", ".join(parts) + "."
    if rec.get("doi"):
        s += f" https://doi.org/{rec['doi']}"
    return s


def format_ieee(rec: dict) -> str:
    bits = []
    for a in rec["authors"][:6]:
        fam, giv = a["family"], a.get("given") or ""
        if re.search(r"[\u4e00-\u9fff]", fam + giv):
            bits.append(fam + giv)
        else:
            ini = initials(giv)
            bits.append(f"{ini} {fam}".strip() if ini else fam)
    if len(rec["authors"]) > 6:
        bits.append("et al.")
    if len(bits) == 1:
        author = bits[0]
    elif len(bits) == 2:
        author = f"{bits[0]} and {bits[1]}"
    else:
        author = ", ".join(bits[:-1]) + ", and " + bits[-1]
    title = rec["title"].rstrip(".")
    journal = rec["journal"] or ""
    s = f'{author}, "{title}," {journal}'
    if rec.get("volume"):
        s += f", vol. {rec['volume']}"
    if rec.get("issue"):
        s += f", no. {rec['issue']}"
    if rec.get("pages"):
        pg = rec["pages"]
        s += (", pp. " if "-" in str(pg) else ", p. ") + str(pg)
    s += f", {rec['year']}"
    if rec.get("doi"):
        s += f", doi: {rec['doi']}"
    return s + "."


def format_bibtex(rec: dict) -> str:
    fam0 = rec["authors"][0]["family"]
    key_base = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", fam0) or "ref"
    key = f"{key_base}{rec['year']}"
    author = " and ".join(
        (a["family"] + ((", " + a["given"]) if a.get("given") else "")).strip().rstrip(",")
        for a in rec["authors"][:8]
    )
    lines = [
        f"@article{{{key},",
        f"  title={{{rec['title'].rstrip('.')}}},",
        f"  author={{{author}}},",
        f"  journal={{{rec['journal'] or ''}}},",
        f"  year={{{rec['year']}}},",
    ]
    if rec.get("volume"):
        lines.append(f"  volume={{{rec['volume']}}},")
    if rec.get("issue"):
        lines.append(f"  number={{{rec['issue']}}},")
    if rec.get("pages"):
        lines.append(f"  pages={{{rec['pages']}}},")
    if rec.get("doi"):
        lines.append(f"  doi={{{rec['doi']}}},")
    # drop trailing comma on last field
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


FORMATTERS = {
    "apa": format_apa,
    "vancouver": format_vancouver,
    "gbt": format_gbt,
    "mla": format_mla,
    "ieee": format_ieee,
    "bibtex": format_bibtex,
    "doi_only": format_doi_only,
    "title_only": format_title_only,
    "pmid_only": format_pmid_only,
}


def author_apa_first(rec: dict) -> str:
    a = rec["authors"][0]
    fam, giv = a["family"], a.get("given") or ""
    if re.search(r"[\u4e00-\u9fff]", fam + giv):
        return fam + giv
    ini = initials(giv)
    return f"{fam}, {ini}".strip().rstrip(",")


def flip_doi_digit(doi: str) -> str:
    """改 DOI 里最后一个数字，得到一个大概率不存在的 DOI。"""
    chars = list(doi)
    for i in range(len(chars) - 1, -1, -1):
        if chars[i].isdigit():
            chars[i] = str((int(chars[i]) + 1) % 10)
            if chars[i] == doi[i]:
                chars[i] = "2" if doi[i] != "2" else "3"
            return "".join(chars)
    return doi + "1"


def doi_exists(doi: str, last: list[float], cache: dict) -> bool | None:
    if doi in cache:
        return cache[doi]
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    try:
        polite(last)
        http_get_json(url)
        cache[doi] = True
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            cache[doi] = False
            return False
        cache[doi] = None
        return None
    except Exception:
        cache[doi] = None
        return None


# ---- public / self fabricated (independent sources) ----

PUBLIC_FAKES = [
    # Walters & Wilder 2023 Appendix 3, work itself is fabricated = 1, type = article
    # filled in later from xlsx by citation_id
]

# Additional documented public cases (already used in the 20-item set; still valid independent sources)
STATIC_PUBLIC = [
    {
        "cite": "Kesselheim AS, Cresswell K. Implementing learning health systems in the UK NHS. BMJ. 2017; 357: j2449. doi: 10.1136/bmj.j2449",
        "expected": "field_mismatch",
        "expect_mismatch_fields": ["doi", "authors", "year", "journal"],
        "source": "JAMA Network Open 2023;6(8):e2327647 Table 2，作者将其列为 GPT-4 虚构条目。https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2808058 ；所给 DOI 10.1136/bmj.j2449 指向另一篇真实文章。",
        "why_expected": "公开报道为虚构条目；题名接近一篇真实文章且 DOI 指向另一篇，按规则应标信息部分不符（或至少不得放行为已验证）。gold 定为 field_mismatch。",
        "language": "en",
        "kind": "public_ai_fake",
    },
    {
        "cite": "Niska R, Hane CA, Castillo RC. Development and validation of the XGBoost prediction model for stroke risk: a large-scale electronic health record-based cohort study. J Stroke Cerebrovasc Dis. 2018;27(9):2413-2422. doi: 10.1016/j.jstrokecerebrovasdis.2018.04.010",
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "同上 JAMA Network Open 2023;6(8):e2327647 Table 2。DOI 10.1016/j.jstrokecerebrovasdis.2018.04.010 实际指向 Lu 等关于动脉斑块的另一篇文章。",
        "why_expected": "题名在库中无对应，DOI 指向另一篇完全不同的文献，按规则应标疑似编造。",
        "language": "en",
        "kind": "public_ai_fake",
    },
    {
        "cite": "Chen, A. C., Martin, A. J., Choy, B., Fernandez-Penas, P., & Dalziell, R. A. (2021). A systematic review of the relationship between sunscreen use and the prevention of melanoma and non-melanoma skin cancer. European Journal of Dermatology, 31(1), 1-9. PMID: 33635047",
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "Cureus 15(5):e39238 Figure 1，原文判定为虚构。https://www.cureus.com/articles/158289-high-rates-of-fabricated-and-inaccurate-references-in-chatgpt-generated-medical-content PMID 33635047 指向另一篇材料化学文章。",
        "why_expected": "题名未找到且 PMID 指向另一篇文章，应标疑似编造。",
        "language": "en",
        "kind": "public_ai_fake",
    },
    {
        "cite": "Kwon, H. H., Yoon, J. Y., Park, S. Y., Min, S., Suh, D. H., & Kim, J. H. (2015). A comprehensive study on the association between diet and skin aging in Korean women. Journal of the American Academy of Dermatology, 73(2), 242-250. PMID: 26183923",
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "同上 Cureus 15(5):e39238 Figure 1，原文判定为虚构。PMID 26183923 指向另一篇生物质气化文章。",
        "why_expected": "题名未找到且 PMID 指向另一篇文章，应标疑似编造。",
        "language": "en",
        "kind": "public_ai_fake",
    },
    {
        "cite": "Telfer, N. R., Colver, G. B., Morton, C. A., & British Association of Dermatologists Therapy Guidelines and Audit Subcommittee. (2009). Guidelines for the management of basal cell carcinoma. British Journal of Dermatology, 161(4), 643-659. PMID: 19663808",
        "expected": "field_mismatch",
        "expect_mismatch_fields": ["year", "volume", "issue", "pages", "pmid"],
        "source": "同上 Cureus Figure 1：原文判定为真实文献但年份、卷期、页码、PMID 不准确。Crossref 正确记录为 2008;159(1):35–48，DOI 10.1111/j.1365-2133.2008.08666.x。",
        "why_expected": "真实文章被改错字段，应标信息部分不符。",
        "language": "en",
        "kind": "public_ai_fake",
    },
    {
        "cite": "梁鳳珍、洪媛媛、林英輝. 心率偏低是否影響身心健康？. 華人心臟雜誌, 2017, 29(3)：221-228.",
        "expected": "not_found",
        "expect_mismatch_fields": [],
        "source": "台湾大学图书馆《ChatGPT自动生成的参考文献真假難辨，不可不慎！》https://tul.blog.ntu.edu.tw/archives/31819 截图 chatgpt-error-1.png 第 1 条；馆员在多馆目录中未找到该刊。",
        "why_expected": "中文条目在 Crossref/OpenAlex 中找不到时只标查无此文，不能确认是假的（本工具不支持知网、万方）。",
        "language": "zh",
        "kind": "public_ai_fake",
    },
    {
        "cite": "郭卉芬、王永年. 不同運動方式對心跳的影響及其健康效益. 中國科技資訊, 2018, 23(17)：18-19.",
        "expected": "not_found",
        "expect_mismatch_fields": [],
        "source": "同上台大图书馆截图第 2 条。",
        "why_expected": "中文条目查不到只标查无此文。",
        "language": "zh",
        "kind": "public_ai_fake",
    },
    {
        "cite": 'Kallajoki M, et al. Homocysteine and bone metabolism. Osteoporos Int. 2002 Oct;13(10):822-7. PMID: 12352394',
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "Alkaissi & McFarlane, Cureus 2023;15(2):e35179，《Artificial Hallucinations in ChatGPT: Implications in Scientific Writing》https://doi.org/10.7759/cureus.35179 。原文写明该题名不存在，PMID 12352394 指向 Grubb 等泌尿外科文章。",
        "why_expected": "公开报道题名不存在且 PMID 张冠李戴，应标疑似编造。",
        "language": "en",
        "kind": "public_ai_fake",
    },
]


SELF_FAB = [
    {
        "cite": "Zhang, L., & Wang, Q. (2022). A unified neural-symbolic framework for automatic literature verification in multilingual academic writing. Journal of Imaginary Computational Linguistics, 18(3), 45–62.",
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "本测试集自造的英文对照样本。期刊 Journal of Imaginary Computational Linguistics 不存在。不能作为可上架依据。",
        "why_expected": "英文信息完整但完全不存在，应标疑似编造。",
        "language": "en",
        "kind": "self_fabricated",
    },
    {
        "cite": "李明、王芳. 基于深度学习的课堂注意力监测研究[J]. 虚构教育研究, 2021, 8(2): 11-20.",
        "expected": "not_found",
        "expect_mismatch_fields": [],
        "source": "本测试集自造的中文对照样本。不能作为可上架依据。",
        "why_expected": "中文自造条目按设计标查无此文，不升格为疑似编造。",
        "language": "zh",
        "kind": "self_fabricated",
    },
    {
        "cite": "Hawthorne, P. L., Reed, M. C., & Okonkwo, T. (2024). A stochastic theory of citation laundering in generative scholarly drafts. Journal of Fictional Scientometrics, 7(2), 88–104.",
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "本测试集自造的英文对照样本。不能作为可上架依据。",
        "why_expected": "英文信息完整但完全不存在，应标疑似编造。",
        "language": "en",
        "kind": "self_fabricated",
    },
    {
        "cite": "赵强, 孙丽. 量子纠缠在中小学课业减负中的应用初探[J]. 虚构物理与教育, 2023, 12(4): 1-9.",
        "expected": "not_found",
        "expect_mismatch_fields": [],
        "source": "本测试集自造的中文对照样本。不能作为可上架依据。",
        "why_expected": "中文自造条目按设计标查无此文。",
        "language": "zh",
        "kind": "self_fabricated",
    },
]


WALTERS_PICK_IDS_BATCH1 = [
    # 选取题名较具体、看起来像完整期刊论文的条目（Appendix 3 中 Work itself is fabricated=1, type=A）
    "4.02", "9.01", "9.04", "10.01", "11.01", "12.03", "13.01",
]
WALTERS_PICK_IDS_BATCH2 = [
    "6.039999999999999", "10.02", "10.04", "13.03", "9.02", "9.03", "4.039999999999999",
]
WALTERS_PICK_IDS_BATCH3 = [
    "10.03", "11.02", "15.01", "17.01", "26.01", "30.01", "34.019999999999996",
]
WALTERS_PICK_IDS_BATCH4 = [
    "17.020000000000003", "21.01", "22.01", "27.01", "32.01", "37.01", "42.019999999999996",
]
WALTERS_PICK_IDS_BATCH5 = [
    "13.02", "19.01", "26.040000000000006", "28.01", "29.01", "38.01", "5.01",
]
WALTERS_PICK_IDS_BATCH6 = [
    "13.04", "18.030000000000005", "22.020000000000003", "31.06000000000001",
    "36.01", "40.029999999999994", "8.03",
]
# 第 7 批：6 条此前未用过的公开编造条目，另加 Geen 2001（已在第 6 批出现）以检测短通用题名撞车
WALTERS_PICK_IDS_BATCH7 = [
    "31.06000000000001",  # Geen, Human aggression / Annual Review of Psychology
    "9.049999999999999",
    "10.049999999999999",
    "14.02",
    "17.030000000000005",
    "18.040000000000006",
    "25.040000000000006",
]


def load_walters_by_ids(ids: list[str]) -> list[dict]:
    path = HERE / "raw" / "sources" / "41598_2023_41032_MOESM3_ESM.xlsx"
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Works cited in those papers"]
    want = set(ids)
    found = {}
    for r in ws.iter_rows(values_only=True):
        cid = str(r[3]) if r[3] is not None else ""
        if cid in want and r[13] == 1 and r[8] == "A":
            found[cid] = {
                "cite": r[4],
                "expected": "suspected_fabricated",
                "expect_mismatch_fields": [],
                "source": (
                    f"Walters & Wilder, Scientific Reports 13:14045 (2023)，Supplementary Appendix 3 "
                    f"citation {cid}，字段「Work itself is fabricated」=1，类型为 article。"
                    f"https://doi.org/10.1038/s41598-023-41032-5 ；原始表见 tests/hundred/raw/sources/。"
                ),
                "why_expected": "公开数据集标注该作品本身为编造的期刊论文（英文、信息完整），按规则应标疑似编造。",
                "language": "en",
                "kind": "public_ai_fake",
                "walters_id": cid,
            }
    missing = [i for i in ids if i not in found]
    if missing:
        raise SystemExit(f"Walters ids not found: {missing}")
    return [found[i] for i in ids]


def assign_formats(n: int, rng: random.Random, recs: list[dict], batch: int = 1) -> list[str]:
    """为 n 条真实文献分配格式，保证多样性。"""
    if batch >= 7:
        # 跨格式检测：APA / MLA / GB/T 7714 / BibTeX / IEEE / Vancouver，以及仅 DOI、仅题名
        labels = (
            ["apa"] * 8
            + ["gbt"] * 6
            + ["vancouver"] * 6
            + ["mla"] * 6
            + ["ieee"] * 6
            + ["bibtex"] * 6
            + ["doi_only"] * 6
            + ["title_only"] * 4
            + ["pmid_only"] * 2
        )
    else:
        # counts: apa 14, gbt 10, vancouver 10, doi_only 8, title_only 6, pmid_only 2
        labels = (
            ["apa"] * 14
            + ["gbt"] * 10
            + ["vancouver"] * 10
            + ["doi_only"] * 8
            + ["title_only"] * 6
            + ["pmid_only"] * 2
        )
    labels = labels[:n]
    while len(labels) < n:
        labels.append("apa")
    rng.shuffle(labels)
    # pmid_only only if we have pmid; we'll swap later
    return labels


def prior_exclusions(current_outdir: Path) -> tuple[set[str], set[str]]:
    """排除此前各批真实/篡改条目的 DOI 与题名，保证新批未见过。"""
    dois: set[str] = set()
    titles: set[str] = set()
    tests_dir = HERE.parent
    cur = current_outdir.resolve()
    for gp in sorted(tests_dir.glob("hundred*/gold.json")):
        if gp.resolve().parent == cur:
            continue
        try:
            data = json.loads(gp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in data.get("items") or []:
            if it.get("group") not in {"real", "tampered"}:
                continue
            rec = it.get("record") or it.get("cited_record") or {}
            doi = (rec.get("doi") or "").strip().lower()
            title = (rec.get("title") or "").strip().lower()
            if doi:
                dois.add(doi)
            if title:
                titles.add(title)
    return dois, titles



def is_quality(rec: dict, *, require_doi: bool) -> bool:
    title = rec.get("title") or ""
    if not title or not rec.get("year"):
        return False
    if "$" in title or "\\" in title or title.rstrip().endswith(":"):
        return False
    if "&amp;" in title or "&amp;" in (rec.get("journal") or ""):
        return False
    if "<" in title or "<" in (rec.get("journal") or ""):
        return False
    for a in rec.get("authors") or []:
        fam = (a.get("family") or "") if isinstance(a, dict) else str(a)
        if fam.count(" ") >= 2:
            return False
        if (fam.count("，") + fam.count("、") + fam.count(",")) >= 1 and len(re.findall(r"[\u4e00-\u9fff]", fam)) >= 4:
            return False
        if len(re.findall(r"[\u4e00-\u9fff]", fam)) >= 5:
            return False
    if require_doi and not rec.get("doi"):
        return False
    if not (rec.get("journal") or "").strip():
        return False
    if is_cjk(title):
        if len(re.findall(r"[\u4e00-\u9fff]", title)) < 8:
            return False
    elif len(title) < 20:
        return False
    return True


def build_items(pool: list[dict], rng: random.Random, batch: int, log: dict, outdir: Path | None = None) -> tuple[list[dict], list[dict]]:
    by_field: dict[str, list[dict]] = {}
    for r in pool:
        by_field.setdefault(r["field"], []).append(r)
    for f in by_field:
        rng.shuffle(by_field[f])

    real_targets = {"medicine": 10, "cs": 10, "physics": 8, "biology": 8, "social": 8, "chinese": 6}
    tamper_targets = {"medicine": 6, "cs": 6, "physics": 5, "biology": 5, "social": 5, "chinese": 3}
    ex_dois, ex_titles = prior_exclusions(Path(outdir) if outdir else HERE)
    log["excluded_from_prior"] = {"dois": len(ex_dois), "titles": len(ex_titles)}

    def seen_before(rec: dict) -> bool:
        doi = (rec.get("doi") or "").strip().lower()
        title = (rec.get("title") or "").strip().lower()
        return bool(doi and doi in ex_dois) or bool(title and title in ex_titles)

    def take(field: str, n: int, require_doi: bool = True) -> list[dict]:
        got = []
        bucket = by_field.get(field) or []
        while bucket and len(got) < n:
            rec = bucket.pop()
            if not is_quality(rec, require_doi=require_doi) or seen_before(rec):
                continue
            got.append(rec)
        return got

    reals = []
    for f, n in real_targets.items():
        got = take(f, n)
        if len(got) < n:
            print(f"WARN real {f}: only {len(got)}/{n}")
        reals.extend(got)
    tampers = []
    for f, n in tamper_targets.items():
        got = take(f, n)
        if len(got) < n:
            print(f"WARN tamper {f}: only {len(got)}/{n}")
        tampers.extend(got)

    leftover = []
    for f, bucket in by_field.items():
        leftover.extend(bucket)
    rng.shuffle(leftover)
    leftover = [r for r in leftover if is_quality(r, require_doi=True) and not seen_before(r)]
    leftover = [r for r in leftover if is_quality(r, require_doi=True)]
    while len(reals) < 50 and leftover:
        reals.append(leftover.pop())
    while len(tampers) < 30 and leftover:
        tampers.append(leftover.pop())

    reals = reals[:50]
    tampers = tampers[:30]
    if len(reals) < 50 or len(tampers) < 30:
        raise SystemExit(f"pool too small: real={len(reals)} tamper={len(tampers)} leftover={len(leftover)}")

    formats = assign_formats(len(reals), rng, reals, batch=batch)
    items = []
    input_lines = []

    # Try to attach PMID for a couple of medical reals via Europe PMC (independent lookup)
    last = [0.0]
    pmid_needed = sum(1 for fm in formats if fm == "pmid_only")
    attached = 0
    for rec, fm in zip(reals, formats):
        if fm == "pmid_only" and not rec.get("pmid") and rec.get("doi"):
            try:
                polite(last)
                q = f'DOI:"{rec["doi"]}"'
                url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
                    {"query": q, "format": "json", "pageSize": 1}
                )
                data = http_get_json(url)
                hits = ((data.get("resultList") or {}).get("result") or [])
                if hits and hits[0].get("pmid"):
                    rec["pmid"] = str(hits[0]["pmid"])
                    rec["pmid_lookup"] = url
                    attached += 1
            except Exception as e:
                rec["pmid_lookup_error"] = str(e)
        if fm == "pmid_only" and not rec.get("pmid"):
            fm = "doi_only" if rec.get("doi") else "apa"

        # title-only: only if title is distinctive (>= 8 words or CJK >= 10 chars)
        if fm == "title_only":
            words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", rec["title"])
            if len(words) < 6:
                fm = "apa"
        if fm == "doi_only" and not rec.get("doi"):
            fm = "apa"

        text = FORMATTERS[fm](rec)
        items.append({
            "id": len(items) + 1,
            "group": "real",
            "expected": "verified",
            "expect_mismatch_fields": [],
            "format": fm,
            "field": rec["field"],
            "language": "zh" if is_cjk(rec["title"]) else "en",
            "source": (
                f"{rec['source']} 记录"
                + (f" DOI {rec['doi']}" if rec.get("doi") else "")
                + (f"；PMID {rec['pmid']}" if rec.get("pmid") else "")
                + f"；{rec['year']}，{rec.get('journal') or ''}。"
                + f" 原始快照：{rec.get('raw_path')}。"
            ),
            "why_expected": "从 Crossref 或 OpenAlex 拉取的真实记录，按库中字段抄录或只保留 DOI/题名/PMID。应标已验证并展示库中记录。",
            "record": {k: rec[k] for k in rec if k != "raw"},
            "cite": text,
        })
        input_lines.append(text)

    log["pmid_attached"] = attached

    # tampers
    tamper_types = (["year"] * 8 + ["authors"] * 6 + ["journal"] * 6 + ["doi"] * 6 + ["pages"] * 4)
    rng.shuffle(tamper_types)
    tamper_types = tamper_types[: len(tampers)]
    doi_cache: dict = {}

    for rec, ttype in zip(tampers, tamper_types):
        rec = json.loads(json.dumps(rec))  # copy
        cited = json.loads(json.dumps(rec))
        note = ""
        fields = [ttype]
        if ttype == "year":
            cited["year"] = rec["year"] + (1 if rec["year"] < 2024 else -1)
            note = f"把年份从 {rec['year']} 改为 {cited['year']}。"
        elif ttype == "authors":
            orig = author_apa_first(rec)
            if is_cjk(rec["title"]):
                cited["authors"] = [{"family": "王伟", "given": ""}] + rec["authors"][1:]
                note = f"把第一作者从「{orig}」改为「王伟」。"
            else:
                cited["authors"] = [{"family": "Smith", "given": "John"}] + rec["authors"][1:]
                note = f"把第一作者从「{orig}」改为「Smith, J.」。"
        elif ttype == "journal":
            orig_j = rec.get("journal") or ""
            # use a real but wrong journal name
            wrong = "Nature" if "nature" not in (orig_j or "").lower() else "Science"
            if is_cjk(orig_j) or is_cjk(rec["title"]):
                wrong = "中华内科杂志" if "内科" not in orig_j else "中华外科杂志"
            cited["journal"] = wrong
            note = f"把期刊从「{orig_j}」改为「{wrong}」。"
        elif ttype == "doi":
            orig = rec.get("doi")
            if not orig:
                # fallback to year
                cited["year"] = rec["year"] + 1
                fields = ["year"]
                note = f"原记录无 DOI，改为把年份从 {rec['year']} 改为 {cited['year']}。"
            else:
                new = flip_doi_digit(orig)
                exists = doi_exists(new, last, doi_cache)
                cited["doi"] = new
                note = f"把 DOI 的一位数字从 {orig} 改为 {new}。"
                if exists is True:
                    note += " 改动后的 DOI 在 Crossref 也能解析（指向另一记录），因此除 DOI 不符外，也可能被判为 DOI 冲突；gold 仍定为 field_mismatch，预期不符字段含 doi。"
                elif exists is False:
                    note += " 已独立查询 Crossref：改动后的 DOI 返回 404，并不指向另一篇文章。"
                else:
                    note += " 未能独立确认改动后 DOI 是否存在（请求异常），gold 仍按「题名能对上、DOI 不符」定为 field_mismatch。"
                cited["doi_exists_after_flip"] = exists
        elif ttype == "pages":
            if rec.get("pages"):
                cited["pages"] = "100-110"
                note = f"把页码从 {rec['pages']} 改为 100-110。"
            elif rec.get("volume"):
                cited["volume"] = str(int(re.sub(r"\D", "1", rec["volume"]) or "1") + 3)
                fields = ["volume"]
                note = f"原页码缺失，改为把卷号从 {rec['volume']} 改为 {cited['volume']}。"
            else:
                cited["year"] = rec["year"] + 1
                fields = ["year"]
                note = f"原页码与卷号缺失，改为把年份从 {rec['year']} 改为 {cited['year']}。"

        text = format_apa(cited)
        items.append({
            "id": len(items) + 1,
            "group": "tampered",
            "expected": "field_mismatch",
            "expect_mismatch_fields": fields,
            "format": "apa",
            "field": rec["field"],
            "language": "zh" if is_cjk(rec["title"]) else "en",
            "tamper": ttype,
            "tamper_note": note,
            "source": (
                f"在真实 {rec['source']} 记录"
                + (f" DOI {rec.get('doi')}" if rec.get("doi") else "")
                + f" 上人为篡改。{note} 原始快照：{rec.get('raw_path')}。自造改错，仅作对照。"
            ),
            "why_expected": "真实文献被改了一个关键字段，题名仍应能对上，应标信息部分不符，并标出被改的字段。",
            "record": rec,
            "cited_record": {k: cited[k] for k in cited if k != "raw"},
            "cite": text,
        })
        input_lines.append(text)

    # fabricated / public AI
    if batch == 1:
        walters_ids = WALTERS_PICK_IDS_BATCH1
    elif batch == 2:
        walters_ids = WALTERS_PICK_IDS_BATCH2
    elif batch == 3:
        walters_ids = WALTERS_PICK_IDS_BATCH3
    elif batch == 4:
        walters_ids = WALTERS_PICK_IDS_BATCH4
    elif batch == 5:
        walters_ids = WALTERS_PICK_IDS_BATCH5
    elif batch == 6:
        walters_ids = WALTERS_PICK_IDS_BATCH6
    else:
        walters_ids = WALTERS_PICK_IDS_BATCH7
    walters = load_walters_by_ids(walters_ids)
    # batch 1: 8 static public + 7 walters + 4 self = 19, add 1 more self or static to make 20
    # 8 static + 7 walters = 15 public, + 4 self = 19. Add one more walters? 8+8+4=20 with 8 walters
    # User asked ~20 completely fabricated OR publicly documented. Mix is fine.
    # Use 8 static + 8 walters + 4 self = 20 for batch 1 if we have 8 walters ids... we have 7. 8+7+5? We have 4 self.
    # 8 static + 7 walters + 4 self = 19. I'll add one more walters id or one more self.
    extra_self = {
        "cite": "Nguyen, T. H., & Patel, R. (2021). Cross-lingual citation graphs for detecting fabricated biomedical claims. Proceedings of the Imaginary Conference on Computational Integrity, 4, 201–218.",
        "expected": "suspected_fabricated",
        "expect_mismatch_fields": [],
        "source": "本测试集自造的英文对照样本。不能作为可上架依据。",
        "why_expected": "英文信息完整但完全不存在，应标疑似编造。",
        "language": "en",
        "kind": "self_fabricated",
    }
    fakes = list(STATIC_PUBLIC) + walters + list(SELF_FAB)
    if len(fakes) < 20:
        fakes.append(extra_self)
    fakes = fakes[:20]
    if batch == 2:
        # use same static public (they're the documented set) + different Walters + same self is ok
        # but "unseen" should be a new 100. For fakes, use different Walters and shuffle self variants.
        pass

    for fk in fakes:
        items.append({
            "id": len(items) + 1,
            "group": fk["kind"],
            "expected": fk["expected"],
            "expect_mismatch_fields": fk.get("expect_mismatch_fields") or [],
            "format": "as_published",
            "field": "public_or_self",
            "language": fk["language"],
            "source": fk["source"],
            "why_expected": fk["why_expected"],
            "cite": fk["cite"],
        })
        input_lines.append(fk["cite"])

    # number 1..N
    for i, it in enumerate(items, 1):
        it["id"] = i

    if len(items) != 100:
        raise SystemExit(f"expected 100 items, got {len(items)}")
    return items, input_lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--seed", default="20261111")
    ap.add_argument("--outdir", default=str(HERE))
    ap.add_argument("--skip-fetch", action="store_true", help="只用已冻结的 raw/ 记录")
    args = ap.parse_args()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    raw_dir = outdir / "raw"

    log = {
        "batch": args.batch,
        "seed": args.seed,
        "started": now_label(),
        "note": "本构造脚本不调用 check_refs.py；gold 依据库中原始记录和条目构造方式，不依据工具输出。",
    }

    pool_path = outdir / "pool.json"
    if args.skip_fetch and pool_path.exists():
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        log["fetch"] = "skipped; loaded pool.json"
        print("loaded pool", len(pool))
    else:
        print("fetching …", now_label())
        pool = fetch_all(raw_dir, log, batch=args.batch)
        pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
        print("pool size", len(pool), "saved", pool_path)

    rng = random.Random(args.seed)
    items, lines = build_items(pool, rng, args.batch, log, outdir)

    gold = {
        "note": (
            f"第 {args.batch} 批 100 条。gold 在运行 check_refs.py 之前写好。"
            f"构造种子 {args.seed}。每条 expected 依据独立来源（Crossref/OpenAlex 快照，或公开报道/自造说明），"
            "不是根据工具输出回填。自造与人为篡改只作对照，不能单独作为可上架依据。"
        ),
        "batch": args.batch,
        "seed": args.seed,
        "constructed_at": now_label(),
        "items": items,
    }
    (outdir / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    # numbered input
    blocks = []
    for i, line in enumerate(lines, 1):
        blocks.append(f"{i}. {line}")
    (outdir / "input.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

    # slim gold view counts
    from collections import Counter
    groups = Counter(it["group"] for it in items)
    expected = Counter(it["expected"] for it in items)
    fields = Counter(it["field"] for it in items)
    langs = Counter(it["language"] for it in items)
    formats = Counter(it.get("format") for it in items)
    log["counts"] = {
        "n": len(items),
        "group": dict(groups),
        "expected": dict(expected),
        "field": dict(fields),
        "language": dict(langs),
        "format": dict(formats),
    }
    log["finished"] = now_label()
    (outdir / "construction.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", outdir / "gold.json", outdir / "input.txt")
    print("counts", json.dumps(log["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次检查结果与预先公开的埋错清单对照。不重跑检查本身。

配对依据是类别和位置（节号、边距方向、或自然语言锚点如「第1章 绪论」「图 4」），
不依赖样例里的【E04】这类测试编号。去掉这些编号后再对照，分数应保持不变。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# 测试编号，对照时忽略，不当作配对依据
MARKER_RE = re.compile(r"【E\d+】")


def strip_markers(s: str) -> str:
    return MARKER_RE.sub("", s or "")


def is_marker_only(s: str) -> bool:
    t = strip_markers(s or "").strip()
    return t == ""


def finding_matches(gold: dict, finding: dict) -> bool:
    m = gold.get("match") or {}
    if m.get("category") and m["category"] != finding.get("category"):
        return False
    if "section" in m and finding.get("section") != m["section"]:
        return False
    if "side" in m and finding.get("side") != m["side"]:
        return False
    if "key" in m and finding.get("key") != m["key"]:
        return False
    if "paragraph_index" in m and finding.get("paragraph_index") != m["paragraph_index"]:
        return False
    # 自然语言锚点（如「第1章 绪论」「图 4」）参与配对；【E04】这类纯编号不参与
    anchor = m.get("anchor")
    if anchor and not is_marker_only(str(anchor)):
        blob = " ".join(
            str(finding.get(k) or "")
            for k in ("paragraph_text", "message", "anchor", "key")
        )
        blob_n = strip_markers(blob)
        anchor_n = strip_markers(str(anchor)).strip()
        if anchor_n and (anchor_n not in blob_n) and (str(anchor) not in blob):
            return False
    return True


def compare(gold_path: Path, findings_path: Path) -> dict:
    gold_doc = json.loads(gold_path.read_text(encoding="utf-8"))
    findings_doc = json.loads(findings_path.read_text(encoding="utf-8"))
    golds = gold_doc["errors"]
    findings = findings_doc.get("findings") or []

    used = set()
    hits = []
    misses = []
    for g in golds:
        matched_i = None
        for i, f in enumerate(findings):
            if i in used:
                continue
            if finding_matches(g, f):
                matched_i = i
                break
        if matched_i is None:
            misses.append(g)
        else:
            used.add(matched_i)
            hits.append({"gold": g, "finding": findings[matched_i]})

    fps = [f for i, f in enumerate(findings) if i not in used]
    result = {
        "n_gold": len(golds),
        "n_findings": len(findings),
        "n_hit": len(hits),
        "n_miss": len(misses),
        "n_false_positive": len(fps),
        "hits": [
            {
                "id": h["gold"]["id"],
                "category": h["gold"]["category"],
                "description": h["gold"]["description"],
                "message": h["finding"]["message"],
            }
            for h in hits
        ],
        "misses": [
            {
                "id": g["id"],
                "category": g["category"],
                "description": g["description"],
                "match": g.get("match"),
            }
            for g in misses
        ],
        "false_positives": [
            {
                "category": f.get("category"),
                "key": f.get("key"),
                "message": f.get("message"),
                "paragraph_text": f.get("paragraph_text"),
                "section": f.get("section"),
                "side": f.get("side"),
            }
            for f in fps
        ],
        "sample_composition": gold_doc.get("sample_composition"),
        "matching": "category+location; marker-only anchors like 【E04】 are ignored",
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True)
    parser.add_argument("--findings", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = compare(Path(args.gold), Path(args.findings))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"预先标注 {result['n_gold']} 处：查出 {result['n_hit']}，"
        f"漏检 {result['n_miss']}，误报 {result['n_false_positive']}。"
    )
    if result["misses"]:
        print("漏检：")
        for m in result["misses"]:
            print(f"  - {m['id']} {m['description']}")
    if result["false_positives"]:
        print("误报：")
        for f in result["false_positives"]:
            print(f"  - {f['category']}: {f['message']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对 hundred 测试结果与预先写好的 gold。不把计数写成准确率。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(gold_path: Path, results_path: Path):
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    return gold, results


def compare(gold: dict, results: list) -> dict:
    items = gold["items"]
    if len(results) != len(items):
        return {"error": f"条数不一致：结果 {len(results)}，标签 {len(items)}"}

    rows = []
    for g, r in zip(items, results):
        exp, got = g["expected"], r["status"]
        ok = got == exp
        # 被改字段是否被标出（仅当预期为 field_mismatch 且实际也是时检查，不单独计为「对错」的硬条件，但记下来）
        exp_fields = set(g.get("expect_mismatch_fields") or [])
        got_fields = {m.get("field") for m in (r.get("mismatched_fields") or [])}
        field_ok = (not exp_fields) or exp_fields.issubset(got_fields)
        rows.append({
            "id": g["id"],
            "group": g["group"],
            "field": g.get("field"),
            "language": g.get("language"),
            "format": g.get("format"),
            "expected": exp,
            "got": got,
            "got_zh": r.get("status_zh"),
            "match": ok,
            "expect_mismatch_fields": sorted(exp_fields),
            "got_mismatch_fields": sorted(x for x in got_fields if x),
            "field_ok": field_ok,
            "notes": r.get("notes") or [],
            "cite": g.get("cite") or r.get("raw"),
        })

    n = len(rows)
    n_ok = sum(1 for x in rows if x["match"])
    n_bad = n - n_ok
    by_group = {}
    for x in rows:
        by_group.setdefault(x["group"], {"n": 0, "ok": 0, "bad": 0})
        by_group[x["group"]]["n"] += 1
        if x["match"]:
            by_group[x["group"]]["ok"] += 1
        else:
            by_group[x["group"]]["bad"] += 1

    zh = [x for x in rows if x["language"] == "zh"]
    en = [x for x in rows if x["language"] != "zh"]
    errors = [x for x in rows if x["got"] == "error"]
    public = [x for x in rows if x["group"] == "public_ai_fake"]
    public_not_verified = sum(1 for x in public if x["got"] != "verified")

    return {
        "n": n,
        "n_ok": n_ok,
        "n_bad": n_bad,
        "by_group": by_group,
        "zh": {
            "n": len(zh),
            "ok": sum(1 for x in zh if x["match"]),
            "bad": sum(1 for x in zh if not x["match"]),
            "got": dict(Counter(x["got"] for x in zh)),
            "expected": dict(Counter(x["expected"] for x in zh)),
        },
        "en": {
            "n": len(en),
            "ok": sum(1 for x in en if x["match"]),
            "bad": sum(1 for x in en if not x["match"]),
        },
        "api_failures": {
            "n_status_error": len(errors),
            "ids": [x["id"] for x in errors],
        },
        "public_ai_fake": {
            "n": len(public),
            "not_verified": public_not_verified,
            "ok": sum(1 for x in public if x["match"]),
        },
        "mismatches": [x for x in rows if not x["match"]],
        "field_not_flagged": [
            x for x in rows
            if x["match"] and x["expected"] == "field_mismatch" and not x["field_ok"]
        ],
        "rows": rows,
        "got_counts": dict(Counter(x["got"] for x in rows)),
        "expected_counts": dict(Counter(x["expected"] for x in rows)),
    }


def main() -> int:
    gold_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "gold.json"
    results_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "results.json"
    gold, results = load(gold_path, results_path)
    rep = compare(gold, results)
    if "error" in rep:
        print(rep["error"])
        return 2
    print("不要把下面的计数写成准确率。这是预先写好的标签与一次联网跑出来的判定对照。")
    print(f"与标签一致 {rep['n_ok']}/{rep['n']}，不一致 {rep['n_bad']}/{rep['n']}。")
    print(f"各状态实际计数：{rep['got_counts']}")
    print(f"接口失败（状态为核查失败）条数：{rep['api_failures']['n_status_error']}，编号：{rep['api_failures']['ids']}")
    print("分组：")
    for k, v in rep["by_group"].items():
        print(f"  {k}: 一致 {v['ok']}/{v['n']}，不一致 {v['bad']}")
    z = rep["zh"]
    print(f"中文条目：{z['n']} 条，一致 {z['ok']}，不一致 {z['bad']}；实际状态 {z['got']}（预期 {z['expected']}）")
    print(f"英文条目：{rep['en']['n']} 条，一致 {rep['en']['ok']}，不一致 {rep['en']['bad']}")
    pub = rep["public_ai_fake"]
    print(f"公开曝光问题条目：{pub['n']} 条，{pub['not_verified']} 条未被放行成已验证；与标签一致 {pub['ok']}")
    if rep["mismatches"]:
        print("\n错判清单：")
        for x in rep["mismatches"]:
            print(
                f"  第 {x['id']:03d} 条 [{x['group']}/{x['language']}/{x.get('field')}] "
                f"预期 {x['expected']}，实际 {x['got']}（{x['got_zh']}）"
            )
            print(f"    引用：{(x['cite'] or '')[:160]}")
            if x["notes"]:
                print(f"    注释：{' / '.join(x['notes'])[:300]}")
    if rep["field_not_flagged"]:
        print("\n状态一致但预期不符字段未被全部标出：")
        for x in rep["field_not_flagged"]:
            print(f"  第 {x['id']:03d} 条 预期字段 {x['expect_mismatch_fields']} 实际 {x['got_mismatch_fields']}")
    out = results_path.with_name("compare.json")
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出 {out}")
    return 0 if rep["n_bad"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

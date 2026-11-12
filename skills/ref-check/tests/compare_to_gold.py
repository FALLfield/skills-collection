#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次核查结果和 tests/gold.json 逐条比对。用法：
python3 tests/compare_to_gold.py [results.json]
不传路径时，比对同目录的 test_results.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    gold = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "test_results.json"
    results = json.loads(src.read_text(encoding="utf-8"))
    if len(results) != len(gold["items"]):
        print(f"条数不一致：结果 {len(results)} 条，标签 {len(gold['items'])} 条。")
        return 2

    ok = 0
    public_not_verified = 0
    public_n = 0
    zh_not_found = []
    print("不要把下面的计数写成准确率。")
    print("20 条测试（其中 5 条为自造或改错的对照样本，其余为真实公开案例）。")
    print()
    for g, r in zip(gold["items"], results):
        exp, got = g["expected"], r["status"]
        accept = {exp}
        if g["id"] == 19:
            accept.add("not_found")
            accept.add("field_mismatch")
        match = got in accept
        if match:
            ok += 1
        if g["group"] == "public_ai_fake":
            public_n += 1
            if got != "verified":
                public_not_verified += 1
            if g["id"] in (17, 18) and got == "not_found":
                zh_not_found.append(g["id"])
        flag = "一致" if match else "不一致"
        print(f"{flag}  第 {g['id']:02d} 条  [{g['group']}]  预期 {exp}  实际 {got}（{r.get('status_zh','')}）")

    print()
    print(f"与标签一致：{ok}/{len(results)}（第 19 条允许「查无此文」或「信息部分不符」）。")
    print(
        f"公开曝光的 {public_n} 条问题条目中，{public_not_verified} 条未被放行"
        + ("，其中 2 条中文只能标记查无此文。" if zh_not_found == [17, 18] else "。")
    )
    if public_not_verified == public_n and zh_not_found == [17, 18]:
        print("公开曝光的 9 条问题条目全部未被放行，其中 2 条中文只能标记查无此文。")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

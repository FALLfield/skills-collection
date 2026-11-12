#!/usr/bin/env python3
"""Draw one overview figure of the 100-item batches. Not an accuracy claim."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "overview_hundred.png"

FONT = None
for fp in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
):
    if Path(fp).exists():
        font_manager.fontManager.addfont(fp)
        FONT = font_manager.FontProperties(fname=fp)
        break

plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"
if FONT:
    plt.rcParams["font.family"] = FONT.get_name()

COLORS = {
    "ok": "#2E7D32",
    "bad": "#C62828",
    "verified": "#2E7D32",
    "field_mismatch": "#F9A825",
    "not_found": "#546E7A",
    "suspected_fabricated": "#C62828",
    "error": "#7E57C2",
}
STATUS_CN = {
    "verified": "已验证",
    "field_mismatch": "信息部分不符",
    "not_found": "查无此文",
    "suspected_fabricated": "疑似编造",
    "error": "核查失败",
}
GROUP_CN = {
    "real": "真实文献",
    "tampered": "人为篡改",
    "public_ai_fake": "公开曝光的问题条目",
    "self_fabricated": "自造对照",
}


def fnt(weight="normal", size=10):
    kw = {"size": size}
    if FONT:
        kw["fontproperties"] = font_manager.FontProperties(
            fname=FONT.get_file(), weight=weight, size=size
        )
    return kw


def main():
    paths = [
        ("第1批", ROOT / "tests/hundred/compare.json", "修通用逻辑之前"),
        ("第2批", ROOT / "tests/hundred_b2/compare.json", "第一轮通用修补后"),
        ("第3批", ROOT / "tests/hundred_b3/compare.json", "第二轮通用修补后"),
        ("第4批", ROOT / "tests/hundred_b4/compare.json", "本轮根因修补后·未见过"),
        ("第5批", ROOT / "tests/hundred_b5/compare.json", "本轮再修补后·未见过"),
        ("第6批", ROOT / "tests/hundred_b6/compare.json", "修 U/V/W/X 之前的未见过批次"),
        ("第7批", ROOT / "tests/hundred_b7/compare.json", "修 U/V/W/X 后·跨格式未见过（只跑一次）"),
    ]
    batches = []
    for name, path, note in paths:
        c = json.loads(path.read_text(encoding="utf-8"))
        c["_name"] = name
        c["_note"] = note
        batches.append(c)

    fig = plt.figure(figsize=(19.2, 12.2), dpi=140)
    fig.suptitle(
        "参考文献核查：在七批各 100 条预先标注样例上的结果（不要读成准确率）",
        fontweight="bold",
        y=0.978,
        **fnt("bold", 15),
    )
    fig.text(
        0.5,
        0.942,
        "对照标签均在运行工具之前独立写好。各批真实/篡改条目与此前各批的 DOI、题名重叠为 0。"
        "公开曝光的问题条目在七批中都没有被放行成「已验证」。"
        "没有任何一批达到 100/100，因此不能写「零差错」。",
        ha="center",
        va="top",
        color="#37474F",
        **fnt(size=9.0),
    )

    ax1 = fig.add_axes([0.05, 0.58, 0.42, 0.31])
    names = [c["_name"] for c in batches]
    oks = [c["n_ok"] for c in batches]
    bads = [c["n_bad"] for c in batches]
    x = np.arange(len(names))
    w = 0.36
    r1 = ax1.bar(x - w / 2, oks, w, color=COLORS["ok"], label="与标签一致")
    r2 = ax1.bar(x + w / 2, bads, w, color=COLORS["bad"], label="与标签不一致")
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, **fnt(size=8.5))
    ax1.set_ylim(0, 125)
    ax1.set_ylabel("条数（每批共 100 条）", **fnt(size=9))
    ax1.set_title("整体：判定 vs 预先标签", loc="left", **fnt("bold", 11))
    ax1.axhline(100, color="#B0BEC5", lw=0.8, ls="--")
    ax1.legend(frameon=False, loc="upper right", prop=fnt(size=8).get("fontproperties"))
    for rects in (r1, r2):
        for rect in rects:
            h = rect.get_height()
            ax1.text(
                rect.get_x() + rect.get_width() / 2,
                h + 1.2,
                f"{int(h)}",
                ha="center",
                va="bottom",
                **fnt("bold", 8.5),
            )
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.text(
        0.5,
        -0.20,
        "七批均未达到「100 篇无差错」，不能写「零差错」。数字只是该批样例上的结果。",
        transform=ax1.transAxes,
        ha="center",
        color=COLORS["bad"],
        **fnt("bold", 8.8),
    )

    ax2 = fig.add_axes([0.52, 0.58, 0.21, 0.31])
    # 真实文献被判成疑似编造/查无此文（硬约束）
    hard = []
    labels = []
    for c in batches:
        n_hard = 0
        for row in c.get("rows") or []:
            if row.get("group") == "real" and row.get("got") in {
                "suspected_fabricated",
                "not_found",
            }:
                n_hard += 1
        # fallback if no rows
        if not c.get("rows"):
            for m in c.get("mismatches") or []:
                if m.get("group") == "real" and m.get("got") in {
                    "suspected_fabricated",
                    "not_found",
                }:
                    n_hard += 1
        hard.append(n_hard)
        labels.append(c["_name"])
    bars = n_b = len(batches)
    bars = ax2.bar(range(n_b), hard, color="#C62828" if any(hard) else "#2E7D32")
    ax2.set_xticks(range(n_b))
    ax2.set_xticklabels(labels, **fnt(size=7.5))
    ax2.set_ylim(0, max(hard + [2]) + 1.5)
    ax2.set_ylabel("条", **fnt(size=8.5))
    ax2.set_title("真实文献被判成\n疑似编造或查无此文", loc="left", **fnt("bold", 10))
    for rect, v in zip(bars, hard):
        ax2.text(
            rect.get_x() + rect.get_width() / 2,
            v + 0.08,
            str(v),
            ha="center",
            va="bottom",
            **fnt("bold", 9),
        )
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.text(
        0.5,
        -0.20,
        "第 1 批 2 条被判查无此文，第 3 批 1 条被判疑似编造；本轮第 4–7 批为 0。",
        transform=ax2.transAxes,
        ha="center",
        color="#546E7A",
        **fnt(size=7.2),
    )

    ax3 = fig.add_axes([0.77, 0.58, 0.20, 0.31])
    zh_ok = [c["zh"]["ok"] for c in batches]
    zh_n = [c["zh"]["n"] for c in batches]
    bars = ax3.bar(range(n_b), zh_ok, color="#EF6C00")
    ax3.set_xticks(range(n_b))
    ax3.set_xticklabels([c["_name"] for c in batches], **fnt(size=7.5))
    ax3.set_ylim(0, 16)
    ax3.set_ylabel("与标签一致的中文条数", **fnt(size=8.5))
    ax3.set_title("中文条目（每批 13 条）", loc="left", **fnt("bold", 10))
    ax3.axhline(13, color="#B0BEC5", lw=0.8, ls="--")
    for rect, o, n in zip(bars, zh_ok, zh_n):
        ax3.text(
            rect.get_x() + rect.get_width() / 2,
            o + 0.2,
            f"{o}/{n}",
            ha="center",
            va="bottom",
            **fnt("bold", 8),
        )
    ax3.spines["top"].set_visible(False)
    ax3.spines["right"].set_visible(False)
    ax3.text(
        0.5,
        -0.20,
        "不支持知网、万方。中文覆盖有限。",
        transform=ax3.transAxes,
        ha="center",
        color="#546E7A",
        **fnt(size=7.2),
    )

    ax4 = fig.add_axes([0.05, 0.10, 0.38, 0.38])
    c6 = batches[-1]
    order = ["verified", "field_mismatch", "not_found", "suspected_fabricated", "error"]
    xpos = np.arange(len(order))
    w = 0.35
    exp = [c6["expected_counts"].get(s, 0) for s in order]
    got = [c6["got_counts"].get(s, 0) for s in order]
    ax4.bar(xpos - w / 2, exp, w, color="#90A4AE", label="预先标签（条）")
    ax4.bar(xpos + w / 2, got, w, color=[COLORS[s] for s in order], label="工具实际判定（条）")
    ax4.set_xticks(xpos)
    ax4.set_xticklabels([STATUS_CN[s] for s in order], **fnt(size=8))
    ax4.set_ylabel("条数（第 7 批 100 条）", **fnt(size=9))
    ax4.set_title("第 7 批（跨格式未见过数据，只跑一次）：各判定档的条数", loc="left", **fnt("bold", 11))
    ax4.legend(frameon=False, loc="upper right", prop=fnt(size=8).get("fontproperties"))
    ax4.spines["top"].set_visible(False)
    ax4.spines["right"].set_visible(False)
    ax4.set_ylim(0, max(exp + got + [1]) * 1.28)
    for i, (e, g) in enumerate(zip(exp, got)):
        ax4.text(i - w / 2, e + 0.5, str(e), ha="center", **fnt(size=8))
        ax4.text(i + w / 2, g + 0.5, str(g), ha="center", **fnt(size=8))

    ax5 = fig.add_axes([0.48, 0.10, 0.49, 0.38])
    ax5.axis("off")
    ax5.set_title("与标签不一致的条目（编号 · 组别 · 标签→判定）", loc="left", **fnt("bold", 11))

    def fmt(m):
        return "{id:>3}  {grp}  {exp} → {got}".format(
            id=m.get("id"),
            grp=GROUP_CN.get(m.get("group"), m.get("group")),
            exp=STATUS_CN.get(m.get("expected"), m.get("expected")),
            got=STATUS_CN.get(m.get("got"), m.get("got")),
        )

    lines = []
    for i, c in enumerate(batches):
        pub = c.get("public_ai_fake") or {}
        api_n = (c.get("api_failures") or {}).get("n_status_error", 0)
        head = f"{c['_name']}（{c['_note']}）：不一致 {c['n_bad']}/100"
        if i < 3:
            # compact for historical batches
            ids = ",".join(str(m.get("id")) for m in (c.get("mismatches") or [])[:12])
            extra = f" 等{c['n_bad']}条" if c["n_bad"] > 12 else ""
            lines.append(head)
            if c["n_bad"]:
                lines.append(f"  编号：{ids}{extra}")
            lines.append(
                f"  公开问题条目被标成已验证：{pub.get('verified', 0)}/{pub.get('n', '—')}；接口失败 {api_n} 条。"
            )
        else:
            lines.append(head)
            ms = c.get("mismatches") or []
            if not ms:
                lines.append("  无。")
            else:
                for m in ms:
                    lines.append("  " + fmt(m))
            lines.append(
                f"  公开问题条目被标成已验证：{pub.get('verified', 0)}/{pub.get('n', '—')}；接口失败 {api_n} 条。"
            )
        lines.append("")
    ax5.text(
        0.0,
        0.99,
        "\n".join(lines),
        va="top",
        ha="left",
        transform=ax5.transAxes,
        linespacing=1.28,
        color="#263238",
        **fnt(size=7.1),
    )

    fig.text(
        0.5,
        0.018,
        "图中每个分数的分母都是该组预先标注的条数，不是准确率。"
        "详情、耗时与构造方法见 tests/REPRODUCE.md。  文件：visuals/overview_hundred.png",
        ha="center",
        color="#546E7A",
        **fnt(size=8),
    )
    fig.savefig(OUT, dpi=140)
    print("wrote", OUT, "size", OUT.stat().st_size)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LaTeX 论文 → 公式可编辑的 Word（docx）。

运行时全部本机完成，不访问网络、不用 GPU、不登录账号、不调用付费接口。
依赖：pandoc 3.x（自带 citeproc）、Python 3.9+、lxml；图片 PDF 转 PNG 需 pdftocairo。

用法：
  python3 latex_to_word.py paper.tex -o paper.docx
  python3 latex_to_word.py /path/to/paper-dir -o paper.docx --report 清单.md
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

# 允许「把本文件所在目录当包根」直接运行
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ltw.flatten import find_main_tex, flatten_inputs  # noqa: E402
from ltw.images import convert_images  # noqa: E402
from ltw.macros import apply_macros, collect_macros, rewrite_known, strip_macro_defs, unwrap_boxes_and_acronyms  # noqa: E402
from ltw.pandoc_run import (  # noqa: E402
    content_sha256, default_csl, find_bib, inspect_docx, postprocess_docx, run_pandoc, write_report,
)
from ltw.refs import (  # noqa: E402
    collect_and_resolve, rewrite_algorithms, stub_tikz, tidy_preamble,
)
from ltw.texfix import (  # noqa: E402
    append_nocite, bib_entry_keys, collect_cite_keys, missing_wrap_captions,
    lowercase_cite_keys_in_tex, normalize_bib_file, sanitize_math, simplify_tables,
    stamp_numbered_equation_markers,
)
from ltw.util import log, sha256_file  # noqa: E402


class ConvertError(Exception):
    """给用户看的一行中文失败信息。"""

VERSION = "0.3.0"


def convert(input_path: Path, output: Path, bib: Optional[str] = None,
            csl: Optional[Path] = None, report: Optional[Path] = None,
            workdir: Optional[Path] = None, keep: bool = False,
            add_eq_numbers: bool = True) -> dict:
    input_path = input_path.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if input_path.is_dir():
        project = input_path
        main = find_main_tex(input_path)
    else:
        project = input_path.parent
        main = input_path

    raw = main.read_text(encoding="utf-8", errors="replace")
    own_work = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="ltw-"))
        own_work = True
    else:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

    try:
        log("[1/6] 展开 \\input（主文件 %s）" % main.name)
        flat = flatten_inputs(raw, main)
        (workdir / "01_flat.tex").write_text(flat, encoding="utf-8")

        log("[2/6] 收集并展开用户宏，改写已知命令")
        macros = collect_macros(flat)
        log("      收集到 %d 个用户宏" % len(macros))
        expanded = strip_macro_defs(flat)
        expanded = apply_macros(expanded, macros)
        expanded = rewrite_known(expanded)
        expanded = rewrite_known(expanded)
        expanded = unwrap_boxes_and_acronyms(expanded)
        expanded = simplify_tables(expanded)
        expanded = sanitize_math(expanded)
        expanded = lowercase_cite_keys_in_tex(expanded)
        (workdir / "02_expanded.tex").write_text(expanded, encoding="utf-8")

        log("[3/6] 解析编号并替换 \\ref / \\eqref / \\cref（先于改写算法，以免丢掉 \\label）")
        resolved, labels, ref_log, num = collect_and_resolve(expanded)
        unresolved_refs = [r for r in ref_log if r.get("status") != "ok"]
        ok_refs = [r for r in ref_log if r.get("status") == "ok"]
        log("      标签 %d 个；引用成功 %d，未解析 %d" % (
            len(labels), len(ok_refs), len(unresolved_refs)))

        log("[4/6] 改写算法 / 占位 TikZ / 转换图片")
        resolved, algo_notes = rewrite_algorithms(resolved)
        resolved, tikz_notes = stub_tikz(resolved)
        resolved, img_ok, img_fail = convert_images(resolved, project, workdir)
        resolved = tidy_preamble(resolved)
        resolved, n_marked = stamp_numbered_equation_markers(resolved)

        bibs = find_bib(project, flat, bib)
        # 规范化：键小写；缺 year/date 的条目补 n.d.，避免 citeproc 静默丢弃
        norm_bibs = []
        norm_bib_text = ""
        for b in bibs:
            try:
                rawb = b.read_text(encoding="utf-8", errors="replace")
                nb = workdir / ("norm_" + b.name)
                nb_text = normalize_bib_file(rawb)
                nb.write_text(nb_text, encoding="utf-8")
                norm_bibs.append(nb)
                norm_bib_text += nb_text + "\n"
            except Exception:
                norm_bibs.append(b)
                try:
                    norm_bib_text += b.read_text(encoding="utf-8", errors="replace") + "\n"
                except Exception:
                    pass
        bibs = norm_bibs or bibs

        cited_keys = collect_cite_keys(resolved)
        known_bib_keys = set(bib_entry_keys(norm_bib_text)) if norm_bib_text else set()
        cited_in_bib = [k for k in cited_keys if (not known_bib_keys) or k in known_bib_keys]
        # 表注里的 \cite 可能随表格一起被丢掉；\nocite 保证条目仍进文献表
        resolved = append_nocite(resolved, cited_in_bib)
        pre_path = workdir / "03_preprocessed.tex"
        pre_path.write_text(resolved, encoding="utf-8")

        log("[5/6] 调用 pandoc（bib: %s）" % [b.name for b in bibs])
        csl_path = csl or default_csl()
        resource = [project, workdir, workdir / "images", main.parent]
        for sub in project.iterdir():
            if sub.is_dir():
                resource.append(sub)
        rc, stderr = run_pandoc(pre_path, output, bibs, csl_path, resource)
        (workdir / "pandoc.stderr").write_text(stderr, encoding="utf-8")
        if rc != 0:
            raise ConvertError(
                "失败：无法解析该 TeX 文件（pandoc 报语法错误或无法处理，退出码 %s）。" % rc
            )
        if not output.exists():
            raise ConvertError("失败：pandoc 已结束但没有生成 docx。")

        log("[6/6] 后处理（公式编号）并检查 docx、写清单")
        pp = postprocess_docx(
            output, n_equations=num.equation, add_eq_numbers=add_eq_numbers,
        )

        log("      后处理：%s" % "; ".join(pp.get("notes") or []))
        doc_info = inspect_docx(output)
        csha = pp.get("content_sha256") or content_sha256(output)
        need_hand = []
        need_hand.extend(tikz_notes)
        need_hand.extend(algo_notes)
        need_hand.extend(img_fail)
        for r in unresolved_refs:
            need_hand.append(
                "交叉引用 \\%s{%s} 未能解析（已写成 %s）" % (
                    r["cmd"], r["key"], r.get("text"))
            )
        for hit in doc_info.get("raw_tex_hits") or []:
            if hit["pattern"] in {"begin", "leftidx", "includegraphics", "exposed_label"}:
                need_hand.append(
                    "docx 中残留 TeX 残片 %s × %d，例如 %s（需手改）" % (
                        hit["pattern"], hit["count"], hit["examples"][:3])
                )
        amp_n = doc_info.get("ampersand_count") or 0
        if amp_n:
            need_hand.append(
                "docx 正文有 %d 处「&」列分隔残片（表结构可能未进入 Word），例如 %s（需手改）" % (
                    amp_n, (doc_info.get("ampersand_leftovers") or [])[:3])
            )
        src_tables = num.table
        word_tables = doc_info.get("tables") or 0
        if src_tables and word_tables < src_tables:
            need_hand.append(
                "源码有 %d 个表环境，Word 中仅 %d 个：有 %d 个表未进入或被拆散，需手改" % (
                    src_tables, word_tables, src_tables - word_tables)
            )
        if not bibs:
            need_hand.append("未找到 .bib 文件，参考文献未生成（需手改或补上 .bib 再转）")
        elif (doc_info.get("bibliography_items") or 0) == 0:
            need_hand.append("已给出 .bib 但 docx 中未检出编号参考文献，需手改")
        docx_bib_n = doc_info.get("bibliography_items") or 0
        cited_n = len(cited_in_bib)
        if bibs and cited_n and docx_bib_n < cited_n:
            need_hand.append(
                "文献被静默丢弃：源码引用 %d 个键（bib 中有对应条目），docx 检出 %d 条（少 %d 条），需手改"
                % (cited_n, docx_bib_n, cited_n - docx_bib_n)
            )
        for note in missing_wrap_captions(resolved, doc_info.get("text") or ""):
            need_hand.append(note)
        qq = doc_info.get("unresolved_qq") or 0
        if qq and not unresolved_refs:
            need_hand.append("docx 中仍有 %d 处「??」，可能是未解析引用，需手改" % qq)
        degraded = ["PDF/EPS 图已转 PNG 嵌入：%s" % s for s in img_ok]
        success = [
            "生成 docx：%s（%d 字节，文件 sha256=%s…，内容级 sha256=%s…）" % (
                output, output.stat().st_size, sha256_file(output)[:16], csha[:16]),
            "OMML 公式：oMath=%s，oMathPara=%s（可在 Word 中编辑）" % (
                doc_info["omath"], doc_info["omath_para"]),
            "表格 %s 个，图片 %s 张" % (doc_info["tables"], doc_info["drawings"]),
            "后处理：%s" % "; ".join(pp.get("notes") or []),
            "交叉引用已解析 %d 处" % len(ok_refs),
        ]
        bib_line = "参考文献：citeproc + %s；docx 内编号条数=%s" % (
            ", ".join(b.name for b in bibs) or "（未找到 bib）",
            doc_info["bibliography_items"],
        )
        if bibs:
            success.append(bib_line)
        else:
            need_hand.append(bib_line)
        counts = {
            "标签数": len(labels),
            "交叉引用已解析": len(ok_refs),
            "交叉引用未解析": len(unresolved_refs),
            "公式计数器（源码编号展示公式）": num.equation,
            "图": num.figure,
            "表": num.table,
            "算法": num.algorithm,
            "docx oMath": doc_info["omath"],
            "docx oMathPara": doc_info["omath_para"],
            "docx 参考文献条数（编号体例）": doc_info["bibliography_items"],
            "源码引用且 bib 中存在的键数": len(cited_in_bib),
            "内容级 sha256": csha,
            "源码表环境": num.table,
            "Word 表": doc_info["tables"],
        }
        meta = {
            "version": VERSION,
            "input": str(main),
            "output": str(output),
            "style": num.style,
            "success": success,
            "degraded": degraded,
            "need_hand": need_hand,
            "counts": counts,
            "pandoc_stderr": stderr,
            "labels": {k: {"kind": v.kind, "number": v.number} for k, v in labels.items()},
            "ref_log": ref_log,
            "doc_info": {k: v for k, v in doc_info.items() if k != "text"},
            "doc_text": doc_info.get("text", ""),
            "bibs": [str(b) for b in bibs],
        }
        if report is None:
            report = output.with_suffix("").parent / (output.stem + ".清单.md")
        write_report(Path(report), meta)
        meta["report"] = str(report)
        slim = {k: v for k, v in meta.items() if k not in {"pandoc_stderr", "doc_text"}}
        slim["pandoc_stderr_len"] = len(stderr)
        json_path = Path(str(report) + ".json")
        json_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
        meta["report_json"] = str(json_path)
        log("完成：%s" % output)
        log("清单：%s" % report)
        return meta
    finally:
        if own_work and not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def _validate_input(path: Path) -> None:
    if not path.exists():
        raise ConvertError("失败：找不到路径：%s" % path)
    if path.is_file():
        suf = path.suffix.lower()
        if suf not in {".tex", ".ltx", ".latex"}:
            raise ConvertError(
                "失败：只接受 .tex 源码（或含 .tex 的目录），拒绝非 tex 输入：%s" % path.name
            )
        if path.stat().st_size == 0:
            raise ConvertError("失败：该 TeX 文件是空的：%s" % path.name)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="LaTeX 论文转 Word（OMML 公式、解析交叉引用、bib 生成参考文献）"
    )
    p.add_argument("input", help="主 .tex 文件或论文源码目录")
    p.add_argument("-o", "--output", required=True, help="输出 docx 路径")
    p.add_argument("--bib", help=".bib 文件（默认自动查找）")
    p.add_argument("--csl", help="CSL 体例文件（默认用附带的 ieee.csl）")
    p.add_argument("--report", help="转换清单路径（默认与 docx 同目录）")
    p.add_argument("--workdir", help="保留中间文件的目录")
    p.add_argument("--keep", action="store_true", help="保留临时中间文件")
    p.add_argument(
        "--no-add-eq-numbers", action="store_true",
        help="不给展示公式补题号（默认会补，与 visuals 右栏一致）",
    )
    args = p.parse_args(argv)
    csl = Path(args.csl) if args.csl else None
    try:
        inp = Path(args.input)
        _validate_input(inp)
        convert(
            inp,
            Path(args.output),
            bib=args.bib,
            csl=csl,
            report=Path(args.report) if args.report else None,
            workdir=Path(args.workdir) if args.workdir else None,
            keep=args.keep,
            add_eq_numbers=not args.no_add_eq_numbers,
        )
    except ConvertError as e:
        print(str(e), file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        missing = e.filename or str(e)
        print("失败：找不到路径：%s" % missing, file=sys.stderr)
        return 1
    except Exception as e:
        text = str(e).strip()
        first = text.splitlines()[0] if text else type(e).__name__
        if first.startswith("失败："):
            print(first, file=sys.stderr)
        elif "找不到含" in first:
            print("失败：%s" % first, file=sys.stderr)
        else:
            print("失败：转换中断：%s" % first, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

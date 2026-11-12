# visuals 生成清单

由 `make_visuals.py` 脚本出图，**非手工拼图**。sha256 可用 `sha256sum` 复核。

## compare_2509.13972_eq.png（第一轮成功样例）

- 含义：左＝官方 PDF 第 3 页；中＝裸 pandoc 第 10 页（可见 `[eq:ppd]` 与残留 `\begin{equation}`）；右＝本工具第 10 页（「Equation 3」、公式题号、Section III-C）。右栏来自第一轮打包的 `tests/outputs/2509.13972/paper.docx`。
- sha256：`cbab4ed995627cd01fe292f5b59aa296e78c0e55d1cba029778194bad39a0bc4`
- 页码：官方 PDF p.3，裸 pandoc p.10，本工具 p.10
- 时间：2026-11-12 16:59（Asia/Macau，UTC+8）

```bash
python3 make_visuals.py \
  --official-pdf tests/samples/2509.13972/official.pdf \
  --bare-docx tests/outputs/2509.13972/bare.docx \
  --ours-docx tests/outputs/2509.13972/paper.docx \
  -o visuals/compare_2509.13972_eq.png \
  --bare-needle '[eq:ppd]' --ours-needle 'Equation' \
  --official-page 3 --bare-page 10 --ours-page 10 \
  --header "LaTeX→Word 对比（arXiv:2509.13972，交叉引用与公式）" \
  --titles "原 PDF,裸 pandoc（标签外露）,本工具"
```

## compare_2509.13972_table.png（第一轮成功样例）

- 含义：左＝官方 PDF 第 6 页（TABLE III）；中＝裸 pandoc 第 14 页（`[tbl_eval]`）；右＝本工具第 14 页（Table III）。
- sha256：`f34b724be60973d03806214c5bf21ff1302925b86d589c154f265f1dcfd90146`
- 页码：官方 PDF p.6，裸 pandoc p.14，本工具 p.14
- 时间：2026-11-12 17:00（Asia/Macau，UTC+8）

```bash
python3 make_visuals.py \
  --official-pdf tests/samples/2509.13972/official.pdf \
  --bare-docx tests/outputs/2509.13972/bare.docx \
  --ours-docx tests/outputs/2509.13972/paper.docx \
  -o visuals/compare_2509.13972_table.png \
  --official-needle 'TABLE III' --bare-needle '[tbl_eval]' --ours-needle 'Table III' \
  --official-page 6 --bare-page 14 --ours-page 14 \
  --header "LaTeX→Word 对比（arXiv:2509.13972，表格交叉引用）" \
  --titles "原 PDF,裸 pandoc（标签外露）,本工具"
```

## compare_2506.21734_tikz.png（重做后新增：降级样例，不是三项全对的那一篇）

- 含义：左＝官方 PDF 第 1 页 Figure 1（有 TikZ 图）；中＝裸 pandoc 第 1 页（图丢失，只剩题注）；右＝本工具第 1 页（写明「[TikZ figure omitted — see conversion report]」，并列入需手改）。
- sha256：`ba756e3f57e2f9180c162779b4a6e1df8aedefe07145e2fd722a1cb193737162`
- 页码：官方 PDF p.1，裸 pandoc p.1，本工具 p.1
- 时间：2026-11-12 17:32（Asia/Macau，UTC+8）

```bash
python3 make_visuals.py \
  --official-pdf tests/samples/2506.21734/official.pdf \
  --bare-docx tests/outputs_redo/2506.21734/bare.docx \
  --ours-docx tests/outputs_redo/2506.21734/paper.docx \
  -o visuals/compare_2506.21734_tikz.png \
  --official-needle 'Figure 1: Left: HRM is inspired' \
  --bare-needle 'Left: HRM is inspired' \
  --ours-needle 'TikZ figure omitted' \
  --official-page 1 --bare-page 1 --ours-page 1 \
  --header "LaTeX→Word 对比（arXiv:2506.21734，TikZ 图降级为占位）" \
  --titles "原 PDF（Figure 1 有图）,裸 pandoc（图丢失，仅题注）,本工具（明确占位，需手改）"
```

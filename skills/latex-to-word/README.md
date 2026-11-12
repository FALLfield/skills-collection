# LaTeX 论文转 Word

把已写好的 LaTeX 论文转成公式可在 Word 里编辑的 docx：解析 `\ref` / `\eqref` / `\cref`，公式走 Word 原生 OMML（不是整页截图），参考文献由 `.bib` 经 pandoc citeproc 生成，并自动写出「成功 / 降级成图片 / 需手改」清单。

运行时全部本机，不访问网络，不用 GPU，不登录账号。

**适合谁：** 需要把已有 LaTeX 稿交给只收 Word 的期刊或学院行政、并能接受复杂表格或 TikZ 仍可能要手改的人。

这不是「一键符合某期刊全部格式」的工具，也不检查文献真伪或降重。

## 怎么用

依赖：pandoc 3.x（须带内置 citeproc）、Python 3.9+ 与 `lxml`、poppler（`pdftocairo`）。出对比图时还要 Pillow 和 LibreOffice。详见 `requirements.txt`。

本机测试用的是 pandoc 3.14（GitHub Release 官方 linux-amd64 包）。

**默认命令会给编号展示公式补题号**，与 `visuals/` 右栏一致。不要加隐藏开关：

```bash
pip install -r requirements.txt   # 若系统已有 lxml、Pillow 可跳过
python3 latex_to_word.py 论文目录或主.tex -o 论文.docx --report 清单.md
```

可选：`--bib refs.bib`、`--csl styles/ieee.csl`、`--workdir 中间文件目录`、`--no-add-eq-numbers`（关掉补号，一般不要用）。

输入必须是 `.tex`（或含 `.tex` 的目录）。若传入 `.txt`、路径不存在、或 tex 无法解析：stderr 打一行中文，以非零退出，不 traceback，不写出 docx。

打开生成的 `清单.md`。缺表、TeX 残片、未解析引用、源码 wraptable/wrapfigure 题注未进入 Word、以及「bib 中被引用的键数多于 docx 文献条数」（文献被静默丢弃）会自动列入「需手改」。「静默丢弃」比对只比条数，查不出文献已进文献表、但正文或题注里的引用处却丢了的情况。

用法示例见 `examples/README.md`。Agent 用法见 `SKILL.md`。

## 哈希如何复核

docx 里的创建时间与临时路径已在后处理中固定；`docProps/custom.xml` 里的 CSL 只保留文件名（如 `ieee.csl`），不含本机绝对路径。对同一输入用上面的默认命令连续跑两次，或把本目录拷到另一处再跑，**整文件 sha256 与内容级 sha256 都应相同**。

内容级 sha256：把 docx 当作 zip，按条目名排序，对每个成员做 sha256 再总哈希（不受 zip 本地时间戳影响）。清单里两项都会写。

实测（2026-11-12，Asia/Shanghai，UTC+8），默认命令对 `tests/samples/2509.13972`：本目录两次、以及拷到另一临时目录再跑一次，整文件 sha256 均为：

- 文件 sha256：`7b2e6937b3ef2d0fa9ceb1fd738f8bf14bd9092a1278f355fbc3710a05e69399`（1817713 字节）
- 内容级 sha256：`f7b388e5f26933541e48abedbd2692cb6d19575883fb5e8d2bc7e5eef4d9f5d8`

产物在 `tests/outputs/2509.13972/paper.docx`（本发布包只带这一代：第三轮测试结果）。

`visuals/compare_2509.13972_*.png` 的右栏来自更早一次转换；哈希见 `visuals/MANIFEST.md`，用脚本重跑对比图可复核 PNG 哈希。

## 在公开源码样例上的结果（不是准确率）

只写实测数字，不写准确率，不写「零差错」。下面三轮都是当时的一次结果，没有为凑数重跑同一批。公式口径在第二轮之后定为：**官方 PDF 中真实编号展示公式的个数**（正文枚举、大 O、文献卷号、年份不算），对比 docx 里带可见 `(n)` 的 `m:oMathPara`。交叉引用看源码 `\ref` / `\eqref` / `\cref` / `\autoref` 次数与是否解析成功；文献看官方 PDF 文末连续编号条数对比 docx 连续编号条数。

本发布包的 `tests/outputs/` 是**第三轮**产物。官方 PDF 不打包，请按 `tests/samples/LICENSE_AND_ATTRIBUTION.md` 的 arXiv 链接下载并用 sha256 核对。

### 第三轮（2026-11-12 约 17:48，Asia/Shanghai）

转换器通用地处理了两件事：给缺 `year`/`date` 的 bib 条目补 `year = {n.d.}`（citeproc 会静默丢掉无日期的 `@misc` 等，stderr 为空），并用 `\nocite` 保住表注里的引用；后处理把 CSL 绝对路径收成 `ieee.csl`。需手改会比较「bib 中被引用的键数」与 docx 文献条数，少了就写「文献被静默丢弃」；该比对只比条数，查不出文献已进文献表、正文引用处却丢了的情况（例如题注未进入 Word）。源码 wraptable/wrapfigure 的题注若在 docx 中缺失，会另行列入需手改。5 篇全部回归重测：

| 样例 | 公式 PDF→docx | 交叉引用 源→已解析 | 文献 PDF→docx | 含义 |
|---|---|---|---|---|
| 2509.13972 | 8=8 | 31=31（失败 0） | 24=24 | **三项对齐**。整文件 sha256 跨目录可复现（见上）。 |
| 2506.21734 | 3=3 | 25=25（0） | 101=101 | **三项对齐**。TikZ 占位，见 visuals。 |
| 2508.16738 | 0=0 | 43=43（0；`eq:plonk`→Section II-C1） | 75=75 | **三项对齐**。源码为无编号 `equation*`。 |
| 2506.04667 | 4=4 | 57=57（0） | **55=55** | **三项对齐**。上一轮因无 year 的 `@misc{nsight-metrics}` 被 citeproc 静默丢掉而为 54；本轮该条进入文献表。 |
| 2611.14518 | 2=2 | 10=10（0） | 26=26 | **三项对齐**。表 4=4。 |

**第三轮 5 篇在裁定口径下三项都对齐。** 需手改仍如实列出（TikZ、算法环境、个别缺图，以及 2506.04667 的 wraptable/wrapfigure 题注未进入 Word——其中两处 `\cite{nsight-metrics}` 在正文中未显示为 `[55]`，该条只在文末文献表出现；2506.21734 的 wrapfigure 题注同样缺失）。本轮没有因文献少条而触发「静默丢弃」（条数已对齐，条数比对不会发现题注里的引用丢失）。

### 第一轮与重做后（历史，本包不再附带那两代 docx）

第一轮（2026-11-12 约 16:56–17:00）：4 篇里只有 2509.13972 三项都对齐。另三篇有公式不对齐、残留 `\begin{equation}`、`eq:plonk`→`??`、文献少 1 等。当时公式还用「PDF 连续括号 `(1)…(K)`」计数，会把枚举或文献卷号算进去。

重做后（约 17:26–17:32）：默认补题号、清残留、修 `eq:plonk` 与 bib 大小写、`tabularx`、需手改自动列出、非 tex 拒绝、同目录哈希可稳定。另加此前未见的 2611.14518，三项 2=2、10=10、26=26，表 4=4。在真实编号公式口径下，公式与交叉引用 5 篇已对齐；**2506.04667 文献仍为 54≠55**（本第三轮已修好）。

许可与署名、官方 PDF 的 arXiv 链接与 sha256 见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`。

## 可视化

由 `make_visuals.py` 出图，非手工拼图。命令与 sha256 见 `visuals/MANIFEST.md`。重跑对比图需要自行下载对应官方 PDF（链接与 sha256 见署名文件）。

- `compare_2509.13972_eq.png`、`compare_2509.13972_table.png`：成功样例（2509）。中栏是裸 pandoc 的真实失败（`[eq:ppd]`、`[tbl_eval]`）；右栏有「Equation 3」与题号。
- `compare_2506.21734_tikz.png`：**降级样例**，不是三项全对才配图。左＝官方 PDF 第 1 页 Figure 1（有 TikZ 图）；中＝裸 pandoc（图丢失，只剩题注）；右＝本工具（写明「[TikZ figure omitted — see conversion report]」，并列入需手改）。sha256：`ba756e3f57e2f9180c162779b4a6e1df8aedefe07145e2fd722a1cb193737162`。

## 已知局限

- 只尽量保住内容结构，**不担保排版符合某期刊**。
- 自定义宏包、TikZ 无法在本工具内编译，清单记为需手改或占位。`tabularx` 会改写成 `tabular`，复杂表仍可能要手改。
- 交叉引用是转换时写下的**静态编号**，不是 Word 域。
- 参考文献默认 IEEE 编号体例，与原文 `.bst` 可能不同。缺 `year`/`date` 的条目会补 `n.d.`，以免被 citeproc 静默丢掉；编号顺序仍可能与原文 bst 不同。「文献被静默丢弃」比对只比条数，查不出文献已进文献表、但正文或题注里的引用处却丢了的情况。
- Word 里统计到的表（docx 中每一个 `w:tbl` 节点，含嵌套表）可能比源码 `table`/`wraptable` 浮动环境多：子图（`subfigure`）或并排插图会被排成图网格表，单元格里用于折行的嵌套 `tabular` 也会单独计数，有的图占位同样会变成单格表。本包样例中，2506.21734 为 0→2（TikZ 占位与「Visualization of intermediate timesteps」那张图被排成单格表），2508.16738 为 9→12（`tab:comp_table` 单元格内 5 个折行用的嵌套 tabular，顶层 7 + 嵌套 5），2506.04667 为 4→12（4 个数据表 + 8 个多子图网格）。
- 「PDF 连续括号 `(1)…(K)`」可能把枚举或卷号算进去，不等于真正的编号展示公式个数。本工具按源码编号展示公式产生 `oMathPara`。
- 上面的数字只说明这些公开样例上发生了什么，不能外推到任意模板。
- OMML「可编辑」由 docx 里存在 `m:oMath` / `m:oMathPara` 确认；对比图用 LibreOffice 在本机渲染。

## 许可

工具代码为 MIT，版权人 Haoxuan XIE，见 `LICENSE`。CSL 体例文件来自 citation-style-language/styles，为 CC BY-SA 3.0，见 `styles/README.md`。测试用论文源码为各作者的 CC BY 4.0 作品，再分发须保留署名与许可，见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`。随源码出现的模板许可也写在同一文件；没有再分发授权的 `llncs.cls` 与 `neurips_2025.sty` 不随包提供，完整 LaTeX 排版时请按该文件中的官方链接下载。

本目录是准备发布的副本，不含密钥或个人账号，运行时不访问网络。

# 测试样例来源与许可

五篇均为 arXiv 上作者选择的 **CC BY 4.0** 论文源码（许可以 arXiv 摘要页 / OAI-PMH 的 `<license>` 为准）。
查阅日期：2026-11-12（Asia/Shanghai，UTC+8），OAI 记录：`https://oaipmh.arxiv.org/oai`。2611.14518 于同日在摘要页核对。
本包仅将它们用作转换测试并附带源码以便复现；再分发时须保留作者署名与许可声明。

许可全文：https://creativecommons.org/licenses/by/4.0/

| arXiv ID | 题名 | 作者（arXiv 记录） | 许可 | 摘要页 |
|---|---|---|---|---|
| 2509.13972 | BIM Informed Visual SLAM for Construction Environments | Asier Bikandi-Noya, Miguel Fernandez-Cortizas, Muhammad Shaheer, Ali Tourani, Holger Voos, Jose Luis Sanchez-Lopez | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | https://arxiv.org/abs/2509.13972 |
| 2506.21734 | Hierarchical Reasoning Model | Guan Wang, Jin Li, Yuhao Sun, Xing Chen, Changling Liu, Yue Wu, Meng Lu, Sen Song, Yasin Abbasi Yadkori | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | https://arxiv.org/abs/2506.21734 |
| 2508.16738 | zkPHIRE: A Programmable Accelerator for ZKPs over HIgh-degRee, Expressive Gates | Alhad Daftardar, Jianqiao Mo, Joey Ah-kiow, Benedikt Bünz, Siddharth Garg, Brandon Reagen | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | https://arxiv.org/abs/2508.16738 |
| 2506.04667 | FlashMoE: Fast Distributed MoE in a Single Kernel | Osayamen Jonathan Aimuyo, Byungsoo Oh, Rachee Singh | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | https://arxiv.org/abs/2506.04667 |
| 2611.14518 | Toward Foundation Detection Models via Example-Based Grounding in EM-DETR | Sheethal Bhat, Bogdan Georgescu, Awais Mansoor, Florin C. Ghesu, Sasa Grbic, Andreas Maier | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | https://arxiv.org/abs/2611.14518 |

源码取自 `https://arxiv.org/e-print/<id>`。官方 PDF 取自 `https://arxiv.org/pdf/<id>`，是与 docx 逐项计数时用的版本。校验和如下（2026-11-12 本机文件）：

| arXiv ID | 字节 | sha256 |
|---|---|---|
| 2509.13972 | 1981283 | `43fd2a46eae6cd4542ccbb1c544c35ef7f3ef0d241480762da9b35ae780a59ef` |
| 2506.21734 | 2138297 | `3c9f7bf4484c8ca1d3cbac5af117afc87cca07e958361cf46904cfa58e2ad19f` |
| 2508.16738 | 947154 | `a946adc2bf7324af4e9fa71ebaadb22f4ee4f92e9cd84c43338cbc2acbea168b` |
| 2506.04667 | 2440702 | `5936a399197ff141bcb5c428e04d8a8032125c6e438247a1d0e4094cbb9b7bfc` |
| 2611.14518 | 1527116 | `c4ea4ba31389ec7987037dad824ca60509b4b3ec600a6d94e698506548d57587` |

发布副本不附带 `official.pdf`：请按上表链接下载并用 sha256 核对。内部测试包仍保留当时用的 PDF 以便复述计数。

覆盖的写作特征（五篇合计，不是每一篇都具备全部特征）：`align` 公式、多栏表（`\multicolumn` / `tabular` / `tabularx`）、自定义 `\newcommand`、子图（`subfigure` / `subfloat`）、`.bib`、图片、TikZ。

不得把这些样例说成「本工具作者的论文」。不得使用无许可稿件。2611.14518 提交于 2026-11-10，13 页，源码 `cvip.tex` / `cvip.bib` 与 5 张 PNG。

## 随源码附带的模板与样式文件

论文的 CC BY 4.0 许可**不覆盖**随源码一起出现的出版社/会议模板。本包对模板按各自文件头中的再分发授权处理，没有授权句的不随包分发。

| 文件 | 所在样例 | 许可 | 本包做法 |
|---|---|---|---|
| `IEEEtran.cls` | `2509.13972/`、`2508.16738/` | 文件头为 [LPPL 1.3](https://www.latex-project.org/lppl/)；官方来源 [CTAN: ieeetran](https://ctan.org/pkg/ieeetran) | 保留（文件内已写明可使用、分发、修改） |
| `ieeetran.bst` | `2509.13972/` | IEEEtran 配套 BibTeX 样式，与 `IEEEtran.cls` 同属该宏包 | 保留 |
| `IEEEtranS.bst` | `2508.16738/` | 文件头为 Perl Artistic License | 保留 |
| `splncs04.bst` | `2611.14518/` | 文件头为 LPPL（由 merlin.mbs 生成） | 保留 |
| `llncs.cls` | 原位于 `2611.14518/` | 随论文源码出现的是 v2.24，**全文无 copyright / license / 再分发授权句**，因此不随本包分发 | 请自行从官方来源下载，放到该样例目录后再做完整 LaTeX 排版 |
| `neurips_2025.sty` | 原位于 `2506.04667/` | 注明 NeurIPS 2025 style，**无 license / copyright 行**，因此不随本包分发 | 请自行从官方来源下载，放到该样例目录后再做完整 LaTeX 排版 |

`llncs.cls` 官方来源：

- Springer LNCS 作者指南：https://www.springer.com/gp/computer-science/lncs/conference-proceedings-guidelines（会转到 Springer 的 Information for Authors 页，从中下载 LaTeX 宏包）
- CTAN 宏包页：https://ctan.org/pkg/llncs

`neurips_2025.sty` 官方来源：

- NeurIPS 2025 样式包：https://media.neurips.cc/Conferences/NeurIPS2025/Styles.zip
- 会议说明：https://neurips.cc/Conferences/2025/PaperInformation/NeurIPS-FAQ

把下载到的 `llncs.cls` 放到 `tests/samples/2611.14518/`，把 `neurips_2025.sty` 放到 `tests/samples/2506.04667/`，即可按原论文源码做完整 LaTeX 排版。

**复现本工具的转换结果不需要这两份模板。** 本包的 `tests/outputs/` 已保存第三轮转换产物；转换器不会把 `.cls` / `.sty` 读进中间 TeX（只解析论文源码）。要核对官方 PDF 的公式/文献计数时，按上文 arXiv 链接下载 PDF 并用 sha256 校验即可，步骤见本文件上部和 `tests/README.md`。

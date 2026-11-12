# 测试样例与实测输出

`samples/` 是 5 篇 arXiv 上 CC BY 4.0 论文的源码（`.tex`、`.bib`、图片）。许可、署名、官方 PDF 的 arXiv 链接与 sha256 见 `samples/LICENSE_AND_ATTRIBUTION.md`。本包不附带官方 PDF，下载后请用该文件中的校验和核对。

`outputs/` 是 2026-11-12（Asia/Shanghai，UTC+8）第三轮测试的产物（本发布包只带这一代）。逐项数字和含义写在根目录 `README.md`。

要重新用本工具转换这 5 篇样例：

```bash
python3 latex_to_word.py tests/samples/<arxiv-id> -o 论文.docx --report 清单.md
```

转换本身不需要再下载出版社/会议模板。`2509.13972` 与 `2508.16738` 中的 `IEEEtran.cls` 已按 LPPL 随包提供；`2611.14518` 的 `llncs.cls` 和 `2506.04667` 的 `neurips_2025.sty` 因原文件没有再分发授权句而不随包提供。若要按原论文源码做完整 LaTeX 排版，请按 `samples/LICENSE_AND_ATTRIBUTION.md` 中的官方链接下载，分别放到对应样例目录。

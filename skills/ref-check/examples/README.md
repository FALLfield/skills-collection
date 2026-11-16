# 案例

三个可直接打开的案例，均来自真实跑过的样例。数字只说明「在这些样例上的结果」，不是准确率。

| 案例 | 解决了什么 | 输入 | 输出 | 对比图 / 截图 |
|---|---|---|---|---|
| [01 混合 6 条](01_mixed_six/) | 一次标出年份写错和问题条目；中文期刊只标「查无此文」 | [input.txt](01_mixed_six/input.txt) | [report.md](01_mixed_six/report.md) | [compare.png](01_mixed_six/compare.png) |
| [02 预先标注 20 条](02_official_twenty/) | 对照事先写好的标签，给出带原文链接的完整报告 | [input.txt](02_official_twenty/input.txt) | [report.html](02_official_twenty/report.html) | [compare.png](02_official_twenty/compare.png) |
| [03 只给 DOI](03_doi_only/) | 只有 DOI 也能查到真实文献，不会误标成疑似编造 | [input.txt](03_doi_only/input.txt) | [report.html](03_doi_only/report.html) | [compare.png](03_doi_only/compare.png) |

根目录仍保留 `input_sample.txt`（与案例 1 相同）和记录跑次的 `output_sample.html` / `output_sample.md`（与案例 2 相同），方便旧链接。完整复现见 `tests/REPRODUCE.md`。

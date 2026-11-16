# 案例

两个可直接打开的案例，内容全部虚构，不是真实学生论文。对照的是 `rules/example_rules.json`（虚构示例，不冒充任何真实学校规范）。

| 案例 | 解决了什么 | 输入 | 输出 | 对比图 |
|---|---|---|---|---|
| [01 预埋 20 处错误](01_official_sample/) | 按规则把格式问题写成 Word 批注并给汇总 | [input.docx](01_official_sample/input.docx) | [annotated.docx](01_official_sample/annotated.docx)、[summary.md](01_official_sample/summary.md) | [compare.png](01_official_sample/compare.png) |
| [02 独立构造的 10 处问题](02_independent_sample/) | 用同一套规则检查另一份短篇稿件 | [input.docx](02_independent_sample/input.docx) | [annotated.docx](02_independent_sample/annotated.docx)、[summary.md](02_independent_sample/summary.md) | [compare.png](02_independent_sample/compare.png) |

在 01 这份样例、这一次跑次上：20 处预先标注的错误都写出了对应批注。不要把这些数字写成准确率。复现步骤见 `tests/REPRODUCE.md`。

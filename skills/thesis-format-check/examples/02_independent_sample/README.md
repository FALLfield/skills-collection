# 案例 2：另一份独立构造的虚构短篇论文

**解决了什么：** 用同一套虚构示例规则，检查一份另行编写、预埋 10 处问题的短篇稿件（页边距、字体字号行距缩进、标题未加粗、章号跳号、题注格式与图号不连续、参考文献缺年份），并写成 Word 批注。

在这 10 条预埋问题的样例上，写出了 10 条问题批注。这只说明「在这份虚构样例、这一次跑次上的结果」，不是准确率。

```bash
python3 check_thesis.py \
  --rules rules/example_rules.json \
  --input examples/02_independent_sample/input.docx \
  --output annotated.docx \
  --summary summary.md
```

- 输入：[`input.docx`](input.docx)（虚构，不是真实学生论文）
- 输出：[`annotated.docx`](annotated.docx)、[`summary.md`](summary.md)
- 对比图：[`compare.png`](compare.png)（左：输入页节选；右：本次写出的 10 条问题摘要。批注在 Word 文件里）

对照规则同样是虚构示例，不冒充任何真实学校规范。检查在本机完成，不上传文档。

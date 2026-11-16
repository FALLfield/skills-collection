# 案例 1：预埋 20 处错误的虚构短篇论文

**解决了什么：** 按一份虚构的示例规则检查毕业论文 `.docx`，把可机读的格式问题写成 Word 批注，并给一页汇总。例如页边距、字体字号、标题跳号、题注格式、页眉页码、手工目录、参考文献缺年份。

测试前公开并冻结了这份虚构样例和 20 处已知错误清单。在这 20 处预先标注的错误上：写出了 20 条对应的 Word 批注；没有「预先标注了但未写出对应批注」的条目；样例里作为正确对照的段落没有被标错。这些数字只说明「在这份虚构样例、这一次跑次上的结果」，不是准确率，也不能外推到任意学校或稿件。

```bash
python3 check_thesis.py \
  --rules rules/example_rules.json \
  --input examples/01_official_sample/input.docx \
  --output annotated.docx \
  --summary summary.md
```

- 输入：[`input.docx`](input.docx)（虚构，不是真实学生论文）
- 输出：[`annotated.docx`](annotated.docx)、[`summary.md`](summary.md)
- 预埋清单：[`sample_errors.md`](sample_errors.md)
- 对比图：[`compare.png`](compare.png)（左栏检查前，右栏同一页加上批注位置示意）

对照规则 `rules/example_rules.json` 是虚构示例，不冒充任何真实学校规范。检查在本机完成，不上传文档。复现步骤见 `tests/REPRODUCE.md`。

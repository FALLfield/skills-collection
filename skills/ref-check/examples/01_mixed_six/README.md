# 案例 1：6 条混合文献（真实、写错、问题条目、中文期刊）

**解决了什么：** 把一份混杂的参考文献一次核查完，标出年份写错和公开报道过的问题条目；中文期刊只标「查无此文」，并不把它写成一定是假的。

输入是 `input.txt` 里的 6 条（也可直接粘进 `ref-check.html`）。判定摘自对完整 20 条测试集的记录跑次，对应其中第 1、7、12、14、16、17 条，不是另一次单独重跑。在这 6 条样例上的结果：已验证 1，信息部分不符 3，疑似编造 1，查无此文 1。

```bash
python3 check_refs.py examples/01_mixed_six/input.txt --mailto you@school.edu -o report.html --md report.md
```

- 输入：[`input.txt`](input.txt)
- 输出：[`report.md`](report.md)
- 对比图：[`compare.png`](compare.png)（六种常见结果的对照）

「查无此文」或「疑似编造」都不等于最终宣判。完整 20 条见 [案例 2](../02_official_twenty/)。

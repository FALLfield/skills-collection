# 案例 2：预先标注的 20 条测试集

**解决了什么：** 在一批事先写好标签的文献上，对照公开库给出带原文链接的报告，方便回头核对每条判定。

输入是 `input.txt`（与 `tests/test_input.txt` 相同），含真实文献、改错对照，以及公开报道过的问题条目。记录跑次的报告摘要为：共 20 条，已验证 6，信息部分不符 6，查无此文 4，疑似编造 4。不要把这些数字写成准确率，也不能外推到任意列表。

```bash
python3 check_refs.py examples/02_official_twenty/input.txt --mailto you@school.edu -o report.html --md report.md
```

- 输入：[`input.txt`](input.txt)
- 输出：[`report.html`](report.html)、[`report.md`](report.md)（记录跑次）
- 截图：[`compare.png`](compare.png)（报告页节选：汇总徽章，以及从第 7 条起的不符 / 疑似编造 / 查无此文）

复现步骤见 `tests/REPRODUCE.md`。第 19 条在不同次查询中可能标成「信息部分不符」或「查无此文」，预先标签允许这一点。

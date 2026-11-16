# 案例 3：只给 DOI

**解决了什么：** 输入里只有 DOI（一条带 `https://doi.org/` 前缀，一条是裸 DOI），也能对上公开库中的记录，而不会因为缺少题名、作者就被标成「疑似编造」。

本目录的报告是 2026-11-16（Asia/Shanghai，UTC+8）当场跑出的结果。在这 2 条样例上的结果：两条都标为「已验证」，都指向同一篇 Nature 2016 的 AlphaGo 论文（https://doi.org/10.1038/nature16961）。

```bash
python3 check_refs.py examples/03_doi_only/input.txt --mailto you@school.edu -o report.html --md report.md
```

- 输入：[`input.txt`](input.txt)
- 输出：[`report.html`](report.html)、[`report.md`](report.md)
- 截图：[`compare.png`](compare.png)

查询会把 DOI 发给 Crossref 等公开接口，不上传全文。需要联网。

# 网页版浏览器实跑

这里记录的是用系统 Chrome 无头模式加载**交付原件** `ref-check.html` 的结果，不能用脚本版代替。

复现（需已安装 Playwright，并用系统 Chrome，不必再下浏览器）：

```bash
python3 tests/html_browser/run_browser_scenarios.py
```

七个场景与截图（本轮 2026-11-11 17:08:47–17:09:44 Asia/Macau，UTC+8，全部 ok）：

- `01_doi_only.png`：仅 `https://doi.org/10.1038/nature16961` → 已验证
- `02_fake_doi.png`：假 DOI `10.99999/acceptance-fake-doi-does-not-exist-20261111` → 查无此文
- `03_pmid_only.png`：仅 `PMID: 26826612` → 已验证（该号的真实记录是 2016 年 *Int J Surg* 的胆囊切除综述，不是 AlphaGo）
- `04_http429.png`：真实 ResNet 条目，用浏览器请求拦截模拟 HTTP 429 → 核查失败/无法下结论
- `05_quoted_title_real_doi.png`：真实文献题名含 “hot Jupiter” 且带 DOI → 已验证，未判疑似编造或查无此文
- `06_title_only_quotes.png`：仅题名含弯引号 → 已验证，未判疑似编造
- `07_cjk_name_order.png`：中文姓名字序「佳 李」+ DOI → 已验证，未判疑似编造或查无此文

结构化结果见 `results.json`。各批结果见仓库 `README.md`。

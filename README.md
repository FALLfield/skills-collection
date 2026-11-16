# Skills 合集

一套可复用的 AI agent skill，每个 skill 是 `skills/` 下的一个独立文件夹，自带说明、脚本、测试和示例。挑你需要的那个下载即可，不必拉整个仓库。

| Skill | 解决什么问题 | 目录 |
|---|---|---|
| 参考文献核查 | 对照 Crossref / OpenAlex / Europe PMC 核查参考文献是否存在、信息是否一致，帮你发现 AI 编造的文献 | [skills/ref-check](skills/ref-check) |
| 搜索后直接看视频 | 把视频变成 agent 看得懂的分镜报告；不能自动下载时给出最短的手动步骤 | [skills/video-watch](skills/video-watch) |
| 毕业论文格式自查 | 按用户提供的学校规范检查毕业论文 `.docx`，把可机读的格式问题写成 Word 批注并给一页汇总 | [skills/thesis-format-check](skills/thesis-format-check) |
| LaTeX 论文转 Word | 把已写好的 LaTeX 论文转成公式可在 Word 里编辑的 docx，并自动写出成功 / 降级成图片 / 需手改清单 | [skills/latex-to-word](skills/latex-to-word) |

## 只下载某一个 skill

```bash
git clone --filter=blob:none --sparse https://github.com/FALLfield/skills-collection.git skills-collection
cd skills-collection
git sparse-checkout set skills/ref-check   # 换成你要的 skill 目录
# 可选目录：skills/ref-check、skills/video-watch、
#           skills/thesis-format-check、skills/latex-to-word
```

然后按该目录里的 `README.md` 和 `SKILL.md` 使用。每个 skill 的局限和真实测试结果都写在它自己的 README 里。

## 案例

每个 skill 目录下的 `examples/` 都有 2–3 个真实跑过的案例（输入、输出或清单、对比图或截图）。数字只说明「在这些样例上的结果」，不是准确率。

| Skill | 案例 | 解决了什么 | 对比图 |
|---|---|---|---|
| 参考文献核查 | [混合 6 条](skills/ref-check/examples/01_mixed_six/)、[20 条测试集](skills/ref-check/examples/02_official_twenty/)、[只给 DOI](skills/ref-check/examples/03_doi_only/) | 标出年份写错和问题条目；只有 DOI 也能查到真实文献 | [6 条](skills/ref-check/examples/01_mixed_six/compare.png)、[20 条](skills/ref-check/examples/02_official_twenty/compare.png)、[DOI](skills/ref-check/examples/03_doi_only/compare.png) |
| 搜索后直接看视频 | [天和 120 秒](skills/video-watch/examples/01_tianhe/)、[神舟二十三号 32 秒](skills/video-watch/examples/02_shenzhou23/) | 口播转写为空也能从画面读硬字幕；竖屏新闻短片拆成分镜联系图 | [天和](skills/video-watch/examples/01_tianhe/compare.png)、[神舟](skills/video-watch/examples/02_shenzhou23/compare.png) |
| 毕业论文格式自查 | [预埋 20 处错误](skills/thesis-format-check/examples/01_official_sample/)、[独立 10 处问题](skills/thesis-format-check/examples/02_independent_sample/) | 按规则把格式问题写成 Word 批注并给汇总 | [20 处](skills/thesis-format-check/examples/01_official_sample/compare.png)、[10 处](skills/thesis-format-check/examples/02_independent_sample/compare.png) |
| LaTeX 转 Word | [公式可编辑](skills/latex-to-word/examples/01_2509_equations/)、[多栏表格](skills/latex-to-word/examples/02_2509_tables/)、[TikZ 降级](skills/latex-to-word/examples/03_2506_tikz/) | 公式成为 Word 里可编辑的 OMML；不能编译的 TikZ 留占位并写入清单 | [公式](skills/latex-to-word/examples/01_2509_equations/compare.png)、[表格](skills/latex-to-word/examples/02_2509_tables/compare.png)、[TikZ](skills/latex-to-word/examples/03_2506_tikz/compare.png) |

## 许可证

本仓库代码为 [MIT](LICENSE)，版权人 Haoxuan XIE。各 skill 目录下也有对应的 `LICENSE`（同样为 MIT，版权人 Haoxuan XIE）。测试样例等第三方材料的许可见各 skill 自己的说明。

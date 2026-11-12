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

## 许可证

本仓库代码为 [MIT](LICENSE)，版权人 Haoxuan XIE。各 skill 目录下也有对应的 `LICENSE`（同样为 MIT，版权人 Haoxuan XIE）。测试样例等第三方材料的许可见各 skill 自己的说明。

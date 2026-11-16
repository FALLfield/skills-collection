# 案例 3：TikZ 图降级并写入清单（arXiv:2506.21734）

**解决了什么：** 遇到无法在本工具内编译的 TikZ 图时，不会静默丢图，而是留下占位，并在清单的「需手改」里写明。其他已导出的 PDF/EPS 图会转成 PNG 嵌入。

在这篇公开样例上的结果：清单登记了 TikZ 占位和一处 wrapfigure 题注未进入 Word；同时有 3 个编号展示公式进入 Word（可编辑）。不要把这些数字写成准确率。

```bash
python3 latex_to_word.py tests/samples/2506.21734 -o paper.docx --report 清单.md
```

- 输入：`tests/samples/2506.21734/`（[Hierarchical Reasoning Model](https://arxiv.org/abs/2506.21734)，Guan Wang 等，CC BY 4.0）
- 输出 docx：`tests/outputs/2506.21734/paper.docx`
- 清单：[`清单.md`](清单.md)（记录跑次，含「降级成图片」与「需手改」）
- 对比图：[`compare.png`](compare.png)

样例源码为作者的 CC BY 4.0 作品，署名与许可见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`。完整输入在 `tests/samples/`，完整 docx 在 `tests/outputs/`，不在本目录重复放置以免仓库体积过大。

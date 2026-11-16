# 案例 1：公式进入 Word 后仍可编辑（arXiv:2509.13972）

**解决了什么：** 把论文里的编号展示公式转成 Word 原生 OMML（可在 Word 里编辑），并补上题号 (1)–(8)。对比图左栏是官方 PDF，中栏是裸 pandoc（公式容易变成残片），右栏是本工具的结果。

在这篇公开样例上的结果：8 个编号展示公式进入 Word，题号为 (1)–(8)；docx 内有可编辑的 `oMath`。不要把这些数字写成准确率，也不能外推到任意模板。

```bash
python3 latex_to_word.py tests/samples/2509.13972 -o paper.docx --report 清单.md
```

- 输入（完整源码）：`tests/samples/2509.13972/`（[BIM Informed Visual SLAM for Construction Environments](https://arxiv.org/abs/2509.13972)，Asier Bikandi-Noya 等，CC BY 4.0）
- 输出 docx：`tests/outputs/2509.13972/paper.docx`
- 清单：[`清单.md`](清单.md)（记录跑次）
- 对比图：[`compare.png`](compare.png)

样例源码为作者的 CC BY 4.0 作品，署名与许可见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`。完整输入在 `tests/samples/`，完整 docx 在 `tests/outputs/`，不在本目录重复放置以免仓库体积过大。

# 案例 2：多栏表格进入 Word（同一篇 arXiv:2509.13972）

**解决了什么：** 把论文中的表格转到 Word，并与官方 PDF、裸 pandoc 对照。公式案例见 [案例 1](../01_2509_equations/)。

在这篇公开样例上的结果：表格进入了 docx（详见清单与对比图）。复杂表格仍可能需要手改，以清单为准。

命令与案例 1 相同，同一次转换同时得到公式和表格：

```bash
python3 latex_to_word.py tests/samples/2509.13972 -o paper.docx --report 清单.md
```

- 输入：`tests/samples/2509.13972/`（同上，CC BY 4.0）
- 输出 docx：`tests/outputs/2509.13972/paper.docx`
- 清单：[`清单.md`](清单.md)
- 对比图：[`compare.png`](compare.png)

样例源码为作者的 CC BY 4.0 作品，署名与许可见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`。完整输入在 `tests/samples/`，完整 docx 在 `tests/outputs/`，不在本目录重复放置以免仓库体积过大。

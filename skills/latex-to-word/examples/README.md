# 案例

三个可直接打开的案例，均来自公开的 CC BY 4.0 论文源码上的记录跑次。完整输入在 `tests/samples/`，完整 docx 在 `tests/outputs/`。数字只说明「在这些公开样例上的结果」，不是准确率。

| 案例 | 解决了什么 | 清单 | 对比图 |
|---|---|---|---|
| [01 公式可编辑（2509.13972）](01_2509_equations/) | 编号公式转为 Word 原生 OMML，并补题号 | [清单.md](01_2509_equations/清单.md) | [compare.png](01_2509_equations/compare.png) |
| [02 多栏表格（2509.13972）](02_2509_tables/) | 表格进入 Word，与官方 PDF、裸 pandoc 对照 | [清单.md](02_2509_tables/清单.md) | [compare.png](02_2509_tables/compare.png) |
| [03 TikZ 降级（2506.21734）](03_2506_tikz/) | 不能编译的 TikZ 留占位，并写进需手改清单 | [清单.md](03_2506_tikz/清单.md) | [compare.png](03_2506_tikz/compare.png) |

署名与许可见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`。更高分辨率的对比图还在 `visuals/`（体积较大）。

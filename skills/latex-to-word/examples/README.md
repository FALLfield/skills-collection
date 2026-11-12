# 示例

用附带的公开样例跑一次（arXiv:2509.13972，CC BY 4.0；署名见 `tests/samples/LICENSE_AND_ATTRIBUTION.md`）。默认命令会补公式题号：

```bash
# 在本目录的上一级（包根）执行
python3 latex_to_word.py tests/samples/2509.13972 -o examples/2509.13972.docx --report examples/2509.13972.清单.md
```

打开生成的 docx，抽查公式是否能在 Word 里编辑、是否有题号 (1)–(8)、正文是否出现「Equation 3」「Section III-C」「Table III」，以及文末是否有 24 条参考文献。对照清单看「需手改」。

若只想看已经测过的结果：本包 `tests/outputs/2509.13972/` 是第三轮测试的产物（默认命令、整文件 sha256 跨目录可复核）。不必为凑数重跑。数字和含义写在根目录 `README.md`。

与裸 pandoc 的差别见 `visuals/compare_2509.13972_eq.png`。TikZ 降级见 `visuals/compare_2506.21734_tikz.png`。

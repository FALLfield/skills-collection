# 可视化生成记录

本文件由 `visuals/generate_visual.py` 写出，记录命令、版本与 sha256，供复核。
图是脚本生成的，不是手工拼图。

## 命令

```bash
python3 visuals/generate_visual.py \
  --before tests/sample_thesis.docx \
  --after tests/recorded_run/annotated.docx \
  --findings tests/recorded_run/findings.json \
  --compare tests/recorded_run/compare.json \
  --gold tests/gold_errors.json \
  --out visuals/before_after.png \
  --meta visuals/GENERATE.md \
  --fonts-conf visuals/fonts.conf \
  --dpi 150
```

内部调用：

```
soffice --headless --norestore --nologo --nolockcheck -env:UserInstallation=file:///tmp/thesis-visual-release/lo_profile --convert-to pdf --outdir /tmp/thesis-visual-release/pdf tests/sample_thesis.docx
soffice --headless --norestore --nologo --nolockcheck -env:UserInstallation=file:///tmp/thesis-visual-release/lo_profile --convert-to pdf --outdir /tmp/thesis-visual-release/pdf tests/recorded_run/annotated.docx
pdftotext -bbox /tmp/thesis-visual-release/pdf/sample_thesis.pdf /tmp/thesis-visual-release/bbox.xml
```

## 环境

- 时间：2026-11-12 17:09:03 Asia/Macau（UTC+8）
- 耗时：4.5 秒
- LibreOffice：LibreOffice 25.2.3.2 520(Build:2)
- pdftoppm / pdftotext：poppler，DPI=150
- 选用页：[3, 4, 5]

## 说明

- LibreOffice 将 docx 转为 PDF 时不画出 Word 批注气泡，因此右栏在同页渲染之上，由脚本按批注锚点和 `pdftotext -bbox` 坐标补画红色编号框与侧栏气泡。
- 交给用户的输出 docx 里是 python-docx 写入的真正 Word 批注。
- `fonts.conf` 只用于出图时把「宋体 / 黑体 / 楷体」映射到本机 Noto CJK，让字体错误在图上能看出差别；检查脚本读的是 docx 里登记的字体名。

## sha256

下列哈希是各文件**全文**的 sha256。本记录本身不计算、不写入自哈希
（避免「追加自哈希行之前的内容哈希」与整文件哈希对不上）。

| 文件 | 含义 | sha256 |
| --- | --- | --- |
| `tests/sample_thesis.docx` | 埋错样例 | `1b0cfddb7dc8fc40c90981cd8fe5d49381f829226d416361b8444d13f0932940` |
| `tests/recorded_run/annotated.docx` | 带批注文档 | `1addda9ccec0a6025dc5d26e0587041ce3ac599b9ca232328d9eb04b272e9e81` |
| `tests/recorded_run/findings.json` | 检查结果 findings.json | `610e729d10c113ce887493e472bb015d1e28fc78fc811ca0a969f959d863c00e` |
| `tests/recorded_run/compare.json` | 对照结果 compare.json | `6f99558585f26c01112e1b0309f1a2d83c442efa9079b0c2b6755027344a5355` |
| `tests/gold_errors.json` | 预先公开的错误清单 | `5517272076522c8b30fa7e30205c6b2858cf42a68996a9aaebd31bafb75f534f` |
| `visuals/before_after.png` | 本脚本生成的前后对比图 | `fae4abc58aa41f4ccc83170a54cb2fcb5246f63e4784f299186bfc9ecee2a91d` |

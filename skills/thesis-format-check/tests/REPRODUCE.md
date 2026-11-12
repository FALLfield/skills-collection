# 如何复现「在 20 处预先标注错误上的结果」

以下命令在本包根目录运行。不要为了凑数改样例或清单后再重跑同一批。这些数字不是准确率。

样例与清单在检查前已冻结，哈希见 `FROZEN.md`：

- `tests/sample_thesis.docx`
- `tests/gold_errors.json`
- `rules/example_rules.json`

## 检查并对照

```bash
python3 check_thesis.py \
  --rules rules/example_rules.json \
  --input tests/sample_thesis.docx \
  --output /tmp/thesis-repro/annotated.docx \
  --summary /tmp/thesis-repro/summary.md \
  --findings /tmp/thesis-repro/findings.json

python3 tests/compare_to_gold.py \
  --gold tests/gold_errors.json \
  --findings /tmp/thesis-repro/findings.json \
  --out /tmp/thesis-repro/compare.json
```

预期（与冻结后那一次正式跑次相同）：

- 标准输出：`检查完成：20 条问题，写入批注 20 条。`
- 对照：`预先标注 20 处：查出 20，漏检 0，误报 0。`

已记录的那一次输出在 `tests/recorded_run/`（批注时间戳会因重跑而不同，批注文案应相同）。对照脚本按类别和位置配对，不依赖样例中的【E04】等测试编号；从正文去掉这些编号后再检查并对照，分数仍应是查出 20、漏检 0、误报 0。

## 非法输入（一行中文，退出码 2，无 traceback）

```bash
# 非 docx
python3 check_thesis.py --rules rules/example_rules.json --input /tmp/not.docx.txt --output /tmp/o.docx --summary /tmp/s.md

# 规则不是合法 JSON
python3 check_thesis.py --rules /tmp/bad.json --input tests/sample_thesis.docx --output /tmp/o.docx --summary /tmp/s.md

# 规则是 JSON 数组
python3 check_thesis.py --rules /tmp/array.json --input tests/sample_thesis.docx --output /tmp/o.docx --summary /tmp/s.md
```

预期：退出码 2，stderr 一行中文（「无法打开输入文档…」或「规则文件不是合法的 JSON…」或「规则文件必须是 JSON 对象…」），没有 `Traceback`。

规则为 `{}` 时退出码 0，提示「规则为空，未启用任何检查项，未执行格式检查」。

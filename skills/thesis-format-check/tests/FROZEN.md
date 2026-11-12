# 冻结记录（写于检查跑次之前）

时间：2026-11-12 16:52:56 Asia/Macau（UTC+8）

下面是样例、错误清单和示例规则在运行检查**之前**的 sha256。这三份输入从此固定；那一次正式跑次只跑一遍，不因结果而改样例或重跑凑数。

| 文件 | sha256 | 字节 |
| --- | --- | --- |
| `tests/sample_thesis.docx` | `1b0cfddb7dc8fc40c90981cd8fe5d49381f829226d416361b8444d13f0932940` | 41619 |
| `tests/gold_errors.json` | `5517272076522c8b30fa7e30205c6b2858cf42a68996a9aaebd31bafb75f534f` | 5952 |
| `tests/sample_errors.md` | `e0bd3c3137849815841dce9d6d21e2e4f67d23535d8da9f493e3ebc6603944bf` | 2515 |
| `rules/example_rules.json` | `ffd40e3c042195232d1a295c81f8c17543d1e19e8a06149c602aa8e714ff2c38` | 2353 |

预埋错误：20 处（E01–E20），清单见 `gold_errors.json` 与 `sample_errors.md`。

随后对脚本做了不改变这 20 处结果的修补：非法输入改为一行中文报错；空文档的问题数与批注数对齐；空规则的提示；对照脚本改为按类别和位置配对。当前目录里的 `check_thesis.py` 与 `tests/compare_to_gold.py` 是修补后的版本，因此它们的哈希与冻结当时不同。冻结的样例、清单和规则没有改动。

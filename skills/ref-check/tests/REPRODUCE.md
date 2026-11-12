# 如何自己复现这 20 条测试

测试集已经放在本目录，不必另找。请联网。对照公开数据库判断文献是否存在并不稀缺，这里只是让你核对本包实际跑出来的结果。

**不要把结果写成准确率。** 这 20 条测试（其中 5 条为自造或改错的对照样本，其余为真实公开案例）的原来说法是：公开曝光的 9 条问题条目全部未被放行，其中 2 条中文只能标记查无此文。

## 文件

| 文件 | 是什么 |
|---|---|
| `test_input.txt` | 20 条待核参考文献，可直接交给脚本或粘进 `ref-check.html` |
| `gold.json` | 每条的预期状态、组别和来源链接 |
| `test_results.json`、`test_report.html`、`test_report.md` | 本轮脚本跑出的完整结果，供对照 |
| `compare_to_gold.py` | 把你新跑的 JSON 和 `gold.json` 逐条比对 |
| `test_acceptance_fixes.py` | 离线检查：仅 DOI/URL 解析、作者缩写兼容、缺文件中文报错；以及把 API 基址指到 `127.0.0.1:1` 模拟断网 |
| `doi_only_input.txt` | 验收样例：仅 URL / 仅 DOI 的 `10.1038/nature16961` |
| `network_fail_input.txt` | 模拟断网用的真实 ResNet 条目 |

20 条分组：

- 第 1–6 条：真实文献（按 Crossref / OpenAlex 记录抄录）
- 第 7–9 条：在真实文献上故意改错字段（自造对照）
- 第 10–11 条：完全自造的对照样本（第 11 条为中文）
- 第 12–20 条：已公开报道或馆员核实过的问题条目（第 17、18 条为台大图书馆案例中的中文条目；来源见 `gold.json`）

其中第 7–11 条共 5 条是自造或改错的对照样本，不能单独当作可上架依据。第 17、18 条在本工具里预期只能是「查无此文」，因为不支持知网、万方，不能确认中文条目是否为假。

## 复现步骤

在包的根目录（`20261111_ref-check/`）运行：

```bash
python3 check_refs.py tests/test_input.txt \
  --html out/official20_report.html \
  --md  out/official20_report.md \
  --json out/official20_results.json \
  --delay 0.35
```

建议加上 `--mailto 你的邮箱`，这是 Crossref 的礼貌要求。整次大约需要两到三分钟，取决于网络。脚本会把题名或 DOI 发送到 Crossref、OpenAlex、Europe PMC，不上传全文。

然后比对：

```bash
python3 tests/compare_to_gold.py out/official20_results.json
```

不传路径时，默认比对本目录里的 `test_results.json`。

也可以把 `test_input.txt` 的内容粘进 `ref-check.html` 再查一遍。网页版与脚本规则相同，但本轮没有对网页版做同等 20 条计次，所以验收以脚本结果为准。

额外补丁测试（不必联网，除「仅 DOI 的联网确认」外）：

```bash
python3 tests/test_acceptance_fixes.py
python3 check_refs.py tests/doi_only_input.txt --json out/doi_only.json
```

模拟断网时，真实 ResNet 条目应标「核查失败/无法下结论」，不得标「查无此文」。仅 DOI/URL 且能解析时，应标「已验证」并展示库中的 Silver 2016 *Nature* 记录。

## 你应当看到什么

若与本轮标签一致：

- 第 1–6 条为「已验证」
- 第 7–9 条为「信息部分不符」，不符字段分别是年份、页码、作者
- 第 10 条为「疑似编造」（自造英文条目）
- 第 11、17、18 条为「查无此文」（中文；不能据此确认是假的）
- 第 12、16、20 条为「信息部分不符」
- 第 13、14、15 条为「疑似编造」
- 第 19 条允许「查无此文」或「信息部分不符」（本轮实测为「查无此文」）

公开曝光的 9 条（第 12–20 条）都不应被标成「已验证」。数据库记录若有更新，个别字段或相近记录可能变化，但不应把这 9 条放行成已验证。各批结果见上级目录的 `README.md`。

## 网页版浏览器实跑

交付的 `ref-check.html` 必须在真实浏览器里点「开始核查」验证，不能用脚本结果代替。七个场景（仅 DOI、假 DOI、仅 PMID、HTTP 429 拦截，以及弯引号+DOI、仅题名弯引号、中文姓名字序）的复现脚本和截图在 `tests/html_browser/`。2026-11-11 17:08:47–17:09:44 七个场景全部通过；修完 U/V/W/X 及后续格式规则后，于 2026-11-11 23:53:57–23:54:40 Asia/Macau（UTC+8）再次加载交付原件重跑，七个场景仍全部通过（`tests/html_browser/results.json`，all_ok=true）。

---

# 100 条测试集怎么构造、怎么复现

用户要求连续测试 100 篇、没有差错后才可通过。本包因此另建了两批各 100 条的测试集。**对照标签（gold）必须有独立依据，且必须在运行 `check_refs.py` 之前写好**，不得先跑工具再按输出回填标签。

构造脚本是 `tests/hundred/build_batch.py`。它会访问 Crossref / OpenAlex / Europe PMC，**不会调用 `check_refs.py`**。标签只依据：冻结的库记录、人为篡改说明、以及公开报道或自造说明。

## 目录

| 路径 | 是什么 |
|---|---|
| `tests/hundred/` | 第 1 批（种子 `20261111`）。`gold.json` 写于 **2026-11-11 14:27:17 Asia/Macau（UTC+8）**，随后才联网跑工具。 |
| `tests/hundred_b2/` | 第 2 批未见过数据（种子 `20261111-b2`）。`gold.json` 写于 **2026-11-11 14:44:27 Asia/Macau（UTC+8）**，在第 1 批错判已记录、通用逻辑已修补、且本批标签写完之后，才联网跑工具。 |
| `tests/hundred_b3/` | 第 3 批未见过数据（种子 `20261111-b3`）。`gold.json` 写于 **2026-11-11 14:59:01 Asia/Macau（UTC+8）**，在第 2 批错判已记录、又一轮通用解析修补之后、且本批标签写完之后，才联网跑工具。Crossref 使用 `offset+56`，OpenAlex 使用 `page=3`。 |
| 各批的 `input.txt` | 100 条待核参考文献，一行一条（或条目原文） |
| 各批的 `gold.json` | 预先标签、组别、来源、篡改点、冻结记录 |
| 各批的 `construction.json` | 构造起止时间、检索 URL、条目构成计数 |
| 各批的 `pool.json` 与 `raw/` | 从 Crossref / OpenAlex 拉回并冻结的原始记录 |
| `tests/hundred/raw/sources/` | 公开案例来源：Walters & Wilder (2023) 附录 3 的 xlsx（CC BY 4.0）及 `SOURCE_NOTES.md` |
| `tests/hundred/compare_to_gold.py` | 把工具 JSON 和预先 gold 逐条比对 |

两批构成相同（约数按用户要求取整）：真实 50、人为篡改 30、公开曝光的问题条目 15、自造对照 5。学科大致为医学 / 计算机各 16 条（含篡改底本）、物理 / 生物 / 社科各 13 条、中文池 9 条，另加 20 条公开或自造。语言：英文 87、中文 13。格式覆盖 APA、GB/T 7714、Vancouver、仅 DOI、仅题名，第 2 批另有 1 条仅 PMID。

**各批真实/篡改条目互为未见过数据：** 第 1 批有 DOI 的真实/篡改条目 76 个，第 2、第 3 批各 80 个；三批两两 DOI **重叠均为 0**。公开曝光的静态 8 条案例在各批中重复出现（它们是固定的文献来源，不是随机抽样）；Walters 附录选取的编号每批不同。第 3 批选用 10.03、11.02、15.01、17.01、26.01、30.01、34.02（表中浮点编号以附录为准）。

第 1 批有 2 条中文真实文献当时没有 DOI（后来在第 2 批的质量过滤中要求真实/篡改必须有 DOI 和期刊名）。这是构造上的弱点，已在日志里写明，没有事后改第 1 批 gold。

## gold 怎么定（独立依据）

1. **真实文献（约 50 条）**  
   按固定检索式向 Crossref / OpenAlex 拉取期刊论文（医学、计算机、物理、生物、社科；中文另用中文检索式）。记录冻结在 `raw/`。再按种子洗牌，经质量过滤后取出。引用文本按库中题名、作者、年份、期刊、卷期页、DOI/PMID 抄录，或只保留 DOI / 题名 / PMID。  
   **预期：已验证。** 依据是库中已存在的记录，不是工具输出。

2. **人为篡改（约 30 条）**  
   另取真实记录，只改一个关键字段，并在 `tamper_note` 写明篡改点：改年份、改第一作者、改期刊名、改 DOI 的一位数字（并另行查询改动后的 DOI 是否在 Crossref 能解析）、或改页码/卷号。  
   **预期：信息部分不符**，且 `expect_mismatch_fields` 含被改字段。依据是「同一篇真实文献被改了一个字段」。

3. **公开曝光的问题条目（约 15 条）与完全自造对照（约 5 条）**  
   公开案例来自可打开的论文或图书馆说明，条目原文尽量按来源抄录：  
   - JAMA Network Open 2023;6(8):e2327647 Table 2（如 Kesselheim、Niska）  
   - Athaluri 等，Cureus 15(5):e39238（如 Chen、Kwon、Telfer）  
   - 台大图书馆 https://tul.blog.ntu.edu.tw/archives/31819 （两条中文）  
   - Alkaissi & McFarlane，Cureus 2023，PMID 12352394（Kallajoki）  
   - Walters & Wilder，*Scientific Reports* 13:14045 (2023) 附录 3（CC BY 4.0；xlsx 存于 `tests/hundred/raw/sources/`）。第 1 批选用编号 4.02、9.01、9.04、10.01、11.01、12.03、13.01；第 2 批选用 6.04、10.02、10.04、13.03、9.02、9.03、4.04（表中浮点编号以附录为准）。  
   英文、信息完整、来源已说明为编造的条目，预期为「疑似编造」；题名与真实文献接近、来源已说明字段有误的，预期为「信息部分不符」；中文且无法用知网/万方确认的，预期为「查无此文」，**不能据此确认是假的**。  
   自造 5 条只作对照，**不能单独作为可上架依据**。中文自造同样预期为「查无此文」。

质量过滤（第 2 批复测时启用，避免把 TeX、残缺题名、无期刊、无 DOI 的真实记录放进对照）：必须有年份和期刊；真实/篡改必须有 DOI；题名不得含 `$` 或 `\`、不得以冒号结尾；中文题名至少 8 个汉字，英文题名至少 20 个字符。

第 2 批起错开样本窗口：同一组检索式，Crossref 使用 `offset+28*(批号-1)`，OpenAlex 使用 `page=批号`。第 3 批还在构造时丢弃 family 字段里挤进多个姓名、以及未反转义 HTML 实体的脏记录；这只影响新抽样，不改已写下的第 1、第 2 批 gold。

## 不要按工具输出改 gold

比对脚本是 `tests/hundred/compare_to_gold.py`。若判定与标签不一致，记录下来，需要时只修**通用**解析或判定逻辑，然后用**新的一批**复测。已经写下的 gold 不再改去迁就输出。

## 如何自己复现（请联网）

第 1 批：

```bash
python3 check_refs.py tests/hundred/input.txt \
  --json out/hundred_results.json \
  --md  out/hundred_report.md \
  -o out/hundred_report.html \
  --mailto 你的邮箱 --delay 0.4

python3 tests/hundred/compare_to_gold.py \
  tests/hundred/gold.json out/hundred_results.json
```

第 2–7 批把路径换成 `tests/hundred_b2/` 至 `tests/hundred_b7/`。整批大约需要 8–12 分钟，取决于网络。脚本只把题名或 DOI/PMID 发到 Crossref、OpenAlex、Europe PMC，不上传全文。

本机记录的实测（耗时、接口失败次数、逐条对错）汇总在上级目录的 `README.md`，总览图在 `visuals/overview_hundred.png`。数据库记录若有更新，个别字段或相近记录可能变化；不要把一次计数写成准确率，应写成「在 N 条样例上的结果」。

若要重新抽样（会得到另一批文献，不能直接对照本包已写下的 gold）：

```bash
python3 tests/hundred/build_batch.py --batch 3 --seed 你的种子 --outdir tests/hundred_b3
```

## 网页版

100 条结果以 Python 脚本的连续实测为准。网页版规则已尽量对齐（包括仅 DOI/PMID、网络失败、期刊名明显不同、题名相近但并非同一篇、文摘号与弯引号题名、中文姓名字序等），但没有对网页做同等 100 条计次。浏览器实跑场景（含弯引号+DOI、仅题名弯引号、中文姓名字序）见 `tests/html_browser/`。


## 第 4–6 批（2026-11-11 16:02 之后）

本轮又造了三批未见过的 100 条，规则与上相同：gold 先写、不按输出回填；种子分别为 `20261111-b4`、`20261111-b5`、`20261111-b6`；真实/篡改条目与此前各批的 DOI、题名重叠为 0。每批仍是 50 真实 / 30 篡改 / 15 公开曝光 / 5 自造，中文 13 条。构造脚本是 `tests/hundred/build_batch.py`（会排除已有批次的 DOI 和题名）。

实测（不要写成准确率）：第 4 批 95/100（16:15:48 写下标签，16:16:09–16:26:35 跑工具，626 秒，1 次接口失败）；第 5 批 98/100（16:36:15 / 16:36:25–16:46:59，634 秒）；第 6 批 95/100（16:55:56 / 16:56:10–17:06:49，639 秒）。六批都没有 100/100，不能写「零差错」。逐条对照见各批次目录中的 `compare.json`。

复现时把上面的命令里的目录换成对应批次即可。若重新抽样，必须换新种子和新目录，不能直接对照本包已写下的 gold。


### 第 7 批（跨格式未见过数据）

目录：`tests/hundred_b7/`。种子 `20261111-b7`。gold 写于 **2026-11-11 23:22:53 Asia/Macau（UTC+8）**，之后只联网跑一次工具（23:28:59–23:40:26）。构造不调用 `check_refs.py`。与第 1–6 批真实/篡改 DOI、题名重叠为 0。真实条目格式包括 APA、MLA、GB/T 7714、BibTeX、IEEE、Vancouver，以及仅 DOI / 仅题名。复现：

```bash
python3 check_refs.py tests/hundred_b7/input.txt \
  --html tests/hundred_b7/report.html \
  --md  tests/hundred_b7/report.md \
  --json tests/hundred_b7/results.json \
  --delay 0.45

python3 tests/hundred/compare_to_gold.py \
  tests/hundred_b7/gold.json tests/hundred_b7/results.json
```

预先标签与一次实测对照为 89/100（6 条接口失败，5 条真实文献字段解析问题）。不要把这一计数写成准确率，也不要为凑数改 gold 或在同一批上重跑。

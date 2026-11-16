# 搜索后直接看视频（通用 agent 说明）

让任意能读本文件、运行命令行的 agent **看懂画面和硬字幕，不只是听口播**。不依赖某个产品的专有工具（Claude Code、Codex、Cursor、OpenClaw、Hermes、Gemini CLI 等都按同一套命令做）。

当链接不能全自动下载时，不要放弃，也不要去绕过登录：判断档次，把不超过 3 个互斥选项告诉用户，等用户把文件或 cookies.txt 放进 `inbox/` 后再继续。

仅用于学习分析用户有权查看的视频。

可直接粘贴的系统提示见同目录 `AGENTS.md`。

## 前置依赖（一次性）

用户电脑需要：Python 3.10+、[ffmpeg](https://ffmpeg.org/) / ffprobe。不用 GPU。

```bash
cd 20261111_video-watch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 可选（仅 B 站回退，用户自行安装，GPL-3.0）：
# .venv/bin/pip install yutto
```

虚拟环境不必叫 `.venv`。之后用该环境的 `python` 运行本包脚本即可。若没有 `models/`，首次口播转写会联网下载约 145 MB 的 faster-whisper `base` 模型。

先准备收件夹（可重复执行）：

```bash
python scripts/fetch_help.py --init
```

## 一条命令

```bash
# 公开链接（能下就自动下；不能下就给出手动步骤和 JSON）
python scripts/watch_video.py --auto "https://..." --out ./out/run1 --language zh

# 用户已把视频或 cookies.txt 放进 inbox/
python scripts/watch_video.py --auto inbox --out ./out/run1 --language zh

# 本地文件
python scripts/watch_video.py --auto /path/to/clip.mp4 --out ./out/run1 --language zh
```

`--out` 可省略，默认写到包内 `out/auto`。预览某条链接会请用户做哪些步骤（不下载）：

```bash
python scripts/fetch_help.py --url "https://..."
```

## 三档流程（由脚本自动判断）

| 档 | 何时走 | agent 该做什么 |
|----|--------|----------------|
| 档 1 全自动 | 公开链接可以直接下载（本测试中 Wikimedia 稳定可取，YouTube 有时可以） | 等命令结束，打开报告和联系图 |
| 档 2 用户一步操作 | 失败原因是需登录、要 cookie、风控/412/429，或用户已经把文件放进 inbox/ | 把 `user_steps` 原样转述。三个选项是**任选其一**，不是连续做完。等用户说「继续」后再次 `--auto` |
| 档 3 兜底 | 仍然没有视频文件 | 只能根据用户提供的标题、评论、字幕文本整理要点；明确说出看不到画面、出不了分镜图 |

档 2 的三个选项（脚本会按原因和平台写出可直接照做的中文步骤；付费/DRM 不会建议用 cookie 去解锁）：

1. **最省事（推荐）：** 按 `user_steps` 里针对该平台的说明保存或录屏，把文件拖进 `inbox/`。B 站普通稿件通常没有「保存成 mp4」按钮，步骤会引导用系统自带录屏（iPhone 控制中心、Android 快捷设置、Win+G、macOS Shift+Command+5）；抖音 / 小红书则先看分享菜单里有没有「保存到相册」。
2. **或者：** 用户在自己已登录该网站网页版的电脑上运行一条 `yt-dlp --cookies-from-browser …` 命令，把视频下到 `inbox/`。手机 App 的登录态不能直接用。这是用户的浏览器和账号；**agent 不得代跑这条命令，也不得读取浏览器。**
3. **或者：** 用户从官方商店安装开源扩展，自行导出 Netscape 格式 `cookies.txt` 放到 `inbox/cookies.txt`，再让 agent 重试链接。扩展与链接以脚本输出为准（Chrome/Edge：Get cookies.txt LOCALLY；Firefox：cookies.txt）。注明：由用户自行导出、只放在自己机器上、用完可删。**用真实 cookie 重试 B 站 / 抖音 / 小红书是否有效，本包未实测，不得声称有效。**

不要做的事：代取 cookie、绕过登录、破解签名或 DRM、去水印、调用 F2 / Douyin_TikTok_Download_API / XHS-Downloader、编造没看过的画面。

## 输出与 JSON 字段

成功时，`--out` 目录里有 `contact_sheet.png`（联系图，请用读图能力打开）、`timeline.png`、`report.md` / `report.html` / `report.json`、`report_page.png`、`status.json`。

无论成功或失败，标准输出末尾都有一行标记 `[video-watch-status]`，随后是一段 JSON。失败时也会写 `out_dir/status.json`。请解析这段 JSON，不要只看退出码。

| 字段 | 含义 |
|------|------|
| `status` | `ok` 已完成；`need_user` 需要用户做一个简单操作；`failed` 无法继续；`preview` 仅预览步骤、尚未下载 |
| `tier` | `1` 全自动；`2` 需用户操作或已用用户文件；`3` 只能处理文字 |
| `reason_code` | `ok`、`need_cookies`、`login`、`waf`、`ratelimit`、`geo`、`restricted`、`unsupported`、`no_media`、`corrupt`、`other` |
| `message` | 可直接转述给用户的中文说明 |
| `user_steps` | 数组，最多 3 项。每项有 `n`、`kind`、`title`、`detail`。把 `title` 和 `detail` 原样给用户 |
| `can_do_without_video` / `cannot_do_without_video` | 档 3 能做 / 做不到的事 |
| `inbox` / `out_dir` / `url` / `platform` | 路径与来源 |

退出码：`0` 成功；`2` 需要用户操作或未能下载；`1` 文件损坏等处理错误。以 `status` 为准。

## 失败后该对用户说的话

把 `message` 和 `user_steps` 几乎原样说出来，例如：

> 这条链接我没法全自动下载（原因见上）。请你任选一种做法，不是三步都要做：  
> 1. 最省事：按我列出的中文步骤保存或录屏（B 站请用系统自带录屏；抖音 / 小红书可先看分享菜单里有没有「保存到相册」），把视频拖进 `inbox/` 文件夹，然后告诉我「继续」。  
> 2. 或者在你自己已登录该网站网页版的电脑上运行我给你的那条 `yt-dlp --cookies-from-browser` 命令（我不会替你跑，也不会读你的浏览器；手机 App 登录态不能直接用）。  
> 3. 或者从官方商店安装我列出的开源扩展，自行导出 `cookies.txt` 放到 `inbox/`。用完可以删。用真实 cookie 能不能下 B 站 / 抖音 / 小红书，我这边没有实测过，不能保证。  
> 在还没有视频文件之前，我看不了画面和硬字幕，也做不出分镜图；但如果你把标题、评论或字幕文本发给我，我可以先帮你整理要点。

不要说「我已经能直接解析小红书 / 抖音 / B 站链接」。

## 平台预期（实测，不是承诺）

测试结果见 `README.md`。

- Wikimedia 公开文件（直链或文件页）：本测试可全自动取到。
- YouTube 公开视频：有时可以，不作承诺。
- B 站 / 抖音 / 小红书：未登录、无 cookie 时本测试取不到。脚本会给出档 2 步骤。真实登录态 / 真实 cookie **未实测**。

## 看图规则

先打开 `contact_sheet.png` 和 `timeline.png`（或 `report.html`）。先读硬字幕和画面，再看口播转写（可能为空或有错字）。没有打开联系图之前，不要填写真实的画面描述。

展示样例在 `visuals/` 与 [`examples/`](examples/)（天和核心舱 120 秒，CC BY 3.0；神舟二十三号亮相 32 秒，CC BY 4.0，均已署名）。三档决策图：`visuals/tier_flow.png`。失败时给用户的指引样例：`visuals/user_guidance.png`。

## 参考

- 可粘贴提示词：`AGENTS.md`
- 安装与平台表：`README.md`
- 开源下载工具对照：`DOWNLOADERS.md`
- 测试与未测项：`README.md` 的平台表与局限

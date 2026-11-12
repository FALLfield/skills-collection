# 搜索后直接看视频

[English](README_EN.md)

**把任何视频变成 agent 看得懂的分镜报告；不能自动下载时，给你最短的手动步骤。**

让任意能跑命令行的 AI agent（Claude Code、Codex、Cursor、OpenClaw、Hermes、Gemini CLI 等均可）看懂画面和硬字幕，而不只是听口播。链接能直接下就全自动；不能下时，不会去绕过登录，而是请你任选一种简单做法。

本目录是准备发布的副本，**尚未推送到任何公开仓库**。

仅用于学习分析自己有权查看的视频。本工具不登录、不代取 cookie、不从浏览器读取 cookie、不破解签名或 DRM、不去水印，也不接入用于绕过平台防护的开源工具。

代码许可为 [MIT](LICENSE)。展示样例素材是中国新闻网《120秒回顾天和核心舱任务的精彩瞬间》，许可 **CC BY 3.0**（https://creativecommons.org/licenses/by/3.0 ），已署名；与代码许可不同，转载样例请保留署名。

## 你需要准备什么

- 一台普通电脑（**不用显卡**），已安装 Python 3.10+ 和 [ffmpeg](https://ffmpeg.org/)
- 按下面安装一次依赖（只需一次）

```bash
git clone <本仓库地址> video-watch
cd video-watch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

虚拟环境目录不必叫 `.venv`，脚本不会写死这个路径。只要在已安装依赖的环境里运行 `python scripts/watch_video.py` 即可（`yt-dlp` 需在 PATH 里，或与当前 `python` 位于同一 bin 目录）。

若要给 B 站链接做回退，可自行再装（不随仓库分发源码）：

```bash
.venv/bin/pip install yutto        # 推荐的 B 站回退，GPL-3.0
# 可选：.venv/bin/pip install you-get
```

首次做口播转写时，若本机还没有 faster-whisper `base` 模型，会联网从 Hugging Face 下载约 145 MB。

系统字体若已有「Noto Sans CJK SC / 思源黑体 / 微软雅黑 / 苹方」，报告里的中文就不会乱码。

把本目录里的 `SKILL.md` 交给任意 agent，或把 `AGENTS.md` 整段粘进系统提示，即可按同一套命令使用。

## 一条命令

```bash
# 只需一次，创建 inbox/
python scripts/fetch_help.py --init

# 公开链接（能下就自动下；不能下就给出手动步骤和 JSON）
python scripts/watch_video.py --auto "https://..." --out ./out/run1 --language zh

# 用户已把视频或 cookies.txt 放进 inbox/
python scripts/watch_video.py --auto inbox --out ./out/run1 --language zh

# 本地文件
python scripts/watch_video.py --auto /path/to/clip.mp4 --out ./out/run1 --language zh
```

预览某条链接会请用户做哪些步骤（不下载）：

```bash
python scripts/fetch_help.py --url "https://..."
```

跑完后打开 `out/run1/report.html`，或把 `contact_sheet.png` 发给能看图的 AI。无论成功或失败，标准输出末尾都有一行标记 `[video-watch-status]`，随后是一段 JSON。失败时请把 JSON 里的 `user_steps` 原样转述给用户（最多三个**互斥**选项，不是连续三步都要做）。

## 三档流程

| 档 | 何时走 | 该做什么 |
|----|--------|----------|
| 档 1 全自动 | 公开链接可以直接下载（本测试中 Wikimedia 稳定可取，YouTube 有时可以） | 等命令结束，打开报告和联系图 |
| 档 2 用户一步操作 | 失败原因是需登录、要 cookie、风控/412/429，或用户已经把文件放进 inbox/ | 把 `user_steps` 原样转述。三个选项任选其一。等用户说「继续」后再跑 `--auto` |
| 档 3 兜底 | 仍然没有视频文件 | 只能根据用户提供的标题、评论、字幕文本整理要点；明确说出看不到画面、出不了分镜图 |

档 2 的三个选项（付费/DRM 不会建议用 cookie 去解锁）：

1. **最省事（推荐）：** 按脚本针对该平台写出的中文步骤保存或录屏，把文件拖进 `inbox/`。B 站普通稿件通常没有「保存成 mp4」按钮，步骤会引导用系统自带录屏（iPhone 控制中心、Android 快捷设置、Win+G、macOS Shift+Command+5）；抖音 / 小红书可先看分享菜单里有没有「保存到相册」。
2. **或者：** 在你自己已登录该网站**网页版**的电脑上运行一条 `yt-dlp --cookies-from-browser …` 命令，把视频下到 `inbox/`。手机 App 的登录态不能直接用。**agent 不得代跑这条命令，也不得读取浏览器。**
3. **或者：** 从官方商店安装开源扩展（Chrome/Edge：Get cookies.txt LOCALLY；Firefox：cookies.txt），自行导出 Netscape 格式 `cookies.txt` 放到 `inbox/cookies.txt`，再让 agent 重试链接。用完可删。**用真实 cookie 重试 B 站 / 抖音 / 小红书是否有效，本包未实测，不得视为一定有效。**

流程图见 `visuals/tier_flow.png`，失败时的指引样例见 `visuals/user_guidance.png`。

## 实测里哪些链接能直接取到？

测试环境未登录、无真实 cookie。下表以 2026-11-11 的测试为准。

| 平台 | 把链接丢进去？ | 实测摘要 |
|------|----------------|----------|
| Wikimedia 公开文件（直链或文件页） | **本测试可取** | 文件页与 `upload.wikimedia.org` 直链均可全自动取到并生成分镜报告 |
| YouTube 公开视频 | **不作承诺** | 同一环境同一条「Me at the zoo」有时成功、有时因 429 / 机器人校验失败 |
| B 站 | **未登录取不到，不作承诺** | 公开稿在本测试中报 HTTP 412。脚本会给出录屏等中文步骤；真实 cookie 未实测 |
| 抖音 | **未登录取不到** | 公开页返回 403，提示需要 cookie。请保存到相册或录屏后放入 `inbox/` |
| 小红书 | **未登录取不到** | 会被转到登录页。请保存视频或录屏后放入 `inbox/` |

工具对照与不接入某些下载器的原因见 `DOWNLOADERS.md`。

## 输出

- 一张「联系图」`contact_sheet.png`：所有关键帧拼在一起，AI 用读图功能就能看画面和硬字幕
- 一张时间轴 `timeline.png`
- 一份分镜报告（`report.md` / `report.html` / `report.json` / `report_page.png`）和镜头节奏统计
- 口播转写若能识别，会附在分镜旁边；转写失败时仍以画面和硬字幕为主

展示样例在 `examples/output/`，效果图在 `visuals/`。该条口播转写为空，OCR 读出了发射时刻、舱体尺寸等写在画面上的信息。原视频文件不随仓库分发。

## 局限请先看

屏幕字识别会错字（台标尤其容易误读）；没有清晰人声、只有配乐的片子，口播可能完全转不出来——这正是本包把画面和硬字幕放在第一位的原因。画面好不好看懂，还取决于你用的 AI 能不能读那张联系图。抖音、小红书，以及本测试环境中的 B 站，都还不能保证「粘贴链接就能看」；这时请用 inbox/ 里的最短手动步骤，不要指望脚本去绕过登录。

## 请不要做的事

不要登录别人的账号，不要让 agent 从浏览器代取 cookie，不要破解签名、DRM 或去水印，不要调用 F2、Douyin_TikTok_Download_API、XHS-Downloader 或同类绕过防护的工具。不要把 `cookies.txt` 发给别人或发到聊天里。仅分析你有权查看的视频。

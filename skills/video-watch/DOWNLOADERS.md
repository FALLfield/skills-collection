# 开源下载工具对照（查阅 2026-11-11，北京时间 / UTC+8）

数据来自 GitHub 仓库页与最新提交/发行记录，查阅时刻约 2026-11-11 14:22（北京时间，UTC+8）。Star 数为当时仓库显示的整数，不是平均值。时间戳若带 Z，已换算到 UTC+8。

本包只把工具当作**用户自己安装的依赖**来调用，不在交付目录里打包第三方源码。许可证允许再分发，也不等于我们会把源码塞进包里。

## 对照表

| 工具 | 仓库 | Star（查阅日） | 许可证 | 最近活动（UTC+8） | 主要平台 | 登录 / cookie | 风险与是否接入 |
|------|------|----------------|--------|-------------------|----------|---------------|----------------|
| **yt-dlp** | https://github.com/yt-dlp/yt-dlp | 206,780 | Unlicense | 最近推送 2026-11-04 15:16 | 通用（YouTube、B 站、Wikimedia、以及声明支持的数千站点；抖音/小红书提取器存在，但常要 cookie） | 公开内容可不登录；可选用户自备 Netscape cookie 文件。本包**不**使用 `--cookies-from-browser`，也**不**默认开启 TLS impersonate | **已接入（默认优先）**。通用下载器，不是针对某个短视频平台的去水印破解器 |
| **yutto** | https://github.com/yutto-dev/yutto | 2,155 | GPL-3.0 | 最近提交 2026-11-10 03:14 | 仅 B 站（投稿、番剧、课程等） | 未登录可试公开稿（清晰度可能受限）；登录信息由用户自行放到 cookie 文件或 yutto 的 auth 文件。本包若收到 `--cookies`，会写成临时 auth 文件再调用，**不**把凭据放到命令行 | **已接入为 B 站可选回退**（`pip install yutto`）。GPL-3.0，不随包分发源码。会员/付费/番剧不绕过 |
| **you-get** | https://github.com/soimort/you-get | 56,860 | MIT（`LICENSE.txt`） | 最近提交 2025-04-27 23:32（代码维护偏慢） | 曾覆盖 B 站、YouTube 及一批国内站点 | 可选 cookie 文件 | **已接入为末位可选回退**（需用户自行安装）。维护明显慢于 yt-dlp，本轮 B 站实测同样失败 |
| **BBDown** | https://github.com/nilaoda/BBDown | 13,824 | MIT | 仓库**已归档**；默认分支已删除；最近正式发行 1.6.3，发布时间 2024-08-14 23:52（UTC+8） | 仅 B 站 | 支持扫码登录 / cookie 字符串（`-c` 走命令行） | **仅当 PATH 上已有可执行文件时才尝试**。不推荐新装：上游已停更。本包**不会**把 cookie 字符串写进命令行；若用户提供了 cookie 文件，会跳过 BBDown，改走 yt-dlp / yutto |
| lux | https://github.com/iawia002/lux | 31,837 | MIT | 最近提交 2025-12-29 13:52 | B 站、YouTube、优酷、爱奇艺等（Go 独立二进制） | 视站点而定 | **未接入、本轮未实测**。与 yt-dlp 功能重叠，更新频率不如 yt-dlp；本环境 B 站 412 也不是换一个同类解析器就能保证解决（yutto、you-get 同样失败） |
| gallery-dl | https://github.com/mikf/gallery-dl | 20,467 | GPL-2.0 | 最近推送 2026-10-31 19:34 | 以图站、画廊为主（Twitter/Pixiv/Danbooru 等），不是本包要解决的短视频链接问题 | 许多站点需要登录 | **未接入**。目标平台不匹配 |
| F2 | https://github.com/Johnserf-Seed/f2 | 2,733 | Apache-2.0 | 最近提交 2026-10-06 11:17 | 抖音、TikTok、B 站、Twitter、微博等 | 通常需要 cookie；并依赖平台签名参数一类实现来请求接口 | **不接入**。实质是在绕过平台接口防护，留给用户自行判断，本包不调用 |
| Douyin_TikTok_Download_API | https://github.com/Evil0ctal/Douyin_TikTok_Download_API | 21,337 | Apache-2.0 | 最近推送 2026-11-09 21:39 | 抖音、TikTok、B 站；仓库说明写明「无水印视频下载」「self-healing identity pool」 | 采集与去水印为产品目标 | **不接入**。去水印、身份池属于绕过平台防护/水印策略 |
| XHS-Downloader | https://github.com/JoeanAmier/XHS-Downloader | 13,266 | GPL-3.0 | 最近推送 2026-11-07 19:18 | 小红书 / RedNote | 文档写 Cookie 非强制，但未设 Cookie 只能下到低分辨率；示例代码使用 `curl_cffi` 的 `impersonate`（模拟浏览器 TLS 指纹） | **不接入**。模拟浏览器指纹属于绕过平台防护；本包不调用、不打包 |

## 合规边界（硬性）

- 只处理无需登录即可公开访问的视频，或用户用自己的账号、自己导出并放置的 cookie 文件（`--cookies`）。
- 不代取 cookie，不从浏览器读取（不用 `--cookies-from-browser`），不扫码代登，不绕过登录，不破解签名或 DRM，不去水印，不抓私人/仅好友可见内容，不搬运付费内容。
- 若某工具的核心能力是还原签名、模拟浏览器指纹、去水印或维持身份池，如实标注且**不接入**。
- 失败时给出中文原因（需登录、需 cookie、风控/429、地区限制、防火墙 412、会员/付费/DRM），并提示改用 `--file` 或自行提供 cookie 文件。

## 本包实际调用顺序

1. Wikimedia 直链（`upload.wikimedia.org`）→ `curl`
2. Wikimedia 文件页 → 公共 API 解析原文件后 `curl`，失败再试 yt-dlp
3. 其他链接，默认 yt-dlp
4. **仅 B 站**：yt-dlp 失败后再试已安装的 yutto、BBDown、you-get
5. **抖音 / 小红书**：只试 yt-dlp，失败后明确说明不接入 F2 / Douyin_TikTok_Download_API / XHS-Downloader

实测结果见 `README.md` 的平台表。本测试环境未登录条件下，B 站三条工具均失败，**不能**写成「现在已经能直接下 B 站」。

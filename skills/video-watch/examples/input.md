# 示例输入

展示与示例只用许可明确的 Wikimedia 片段，并署名。本例对应测试 3：中国新闻网《120秒回顾天和核心舱任务的精彩瞬间》。

- 许可：**CC BY 3.0**（https://creativecommons.org/licenses/by/3.0 ）
- 作者：中国新闻网
- 文件页：https://commons.wikimedia.org/wiki/File:Review_the_wonderful_moments_of_Tianhe_core_cabin_mission_in_120_seconds.webm
- 时长：121.4 秒，画幅 854×480
- 为何拿它做首图：口播转写为空，但 OCR 读出了发射时刻、舱体尺寸、「发射任务取得圆满成功」等写在画面上的信息，用来说明本包主打「看懂画面和硬字幕」，而不是听口播。

```bash
python scripts/watch_video.py --file /path/to/tianhe.webm \
  --source-url "https://commons.wikimedia.org/wiki/File:Review_the_wonderful_moments_of_Tianhe_core_cabin_mission_in_120_seconds.webm" \
  --title "120秒回顾天和核心舱任务的精彩瞬间" \
  --language zh \
  --credit "中国新闻网《120秒回顾天和核心舱任务的精彩瞬间》，CC BY 3.0，https://creativecommons.org/licenses/by/3.0" \
  --out ./out/tianhe
```

小红书、抖音、B 站链接在未登录时通常不能全自动下载，脚本不会去绕过登录。这时请任选一种简单做法（不是三步都要做）：用平台「保存视频 / 分享」或系统录屏，把文件放进 `inbox/`（或用 `--file`）；或者在自己已登录的电脑上自行导出 `cookies.txt`，或自己运行 `yt-dlp --cookies-from-browser`（agent 不代取、不读浏览器）。用真实 cookie 是否有效，本包未实测，不得视为一定可以。Wikimedia 等公开文件通常可直接 `python scripts/watch_video.py --auto "https://..."`。

仅用于学习分析自己有权查看的视频。对应输出在 `examples/output/`（含署名后的联系图、时间轴和报告；不含原视频文件）。

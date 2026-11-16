# 示例输入

展示与示例只用许可明确的 Wikimedia 片段，并署名。本例对应《120秒回顾天和核心舱任务的精彩瞬间》。

- 许可：**CC BY 3.0**（https://creativecommons.org/licenses/by/3.0 ）
- 作者：中国新闻网
- 文件页：https://commons.wikimedia.org/wiki/File:Review_the_wonderful_moments_of_Tianhe_core_cabin_mission_in_120_seconds.webm
- 时长：121.4 秒，画幅 854×480
- 原视频不随仓库分发

```bash
python scripts/watch_video.py --file /path/to/tianhe.webm \
  --source-url "https://commons.wikimedia.org/wiki/File:Review_the_wonderful_moments_of_Tianhe_core_cabin_mission_in_120_seconds.webm" \
  --title "120秒回顾天和核心舱任务的精彩瞬间" \
  --language zh \
  --credit "中国新闻网《120秒回顾天和核心舱任务的精彩瞬间》，CC BY 3.0，https://creativecommons.org/licenses/by/3.0" \
  --out ./out/tianhe
```

公开的 Wikimedia 文件页通常也可直接：

```bash
python scripts/watch_video.py --auto "https://commons.wikimedia.org/wiki/File:Review_the_wonderful_moments_of_Tianhe_core_cabin_mission_in_120_seconds.webm" \
  --language zh \
  --credit "中国新闻网《120秒回顾天和核心舱任务的精彩瞬间》，CC BY 3.0，https://creativecommons.org/licenses/by/3.0" \
  --out ./out/tianhe
```

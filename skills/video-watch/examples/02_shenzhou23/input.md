# 示例输入

- 标题：现场视频：神舟二十三号航天员首次集体亮相
- 许可：**CC BY 4.0**（https://creativecommons.org/licenses/by/4.0 ）
- 作者：中国新闻社
- 文件页：https://commons.wikimedia.org/wiki/File:现场视频_神舟二十三号航天员首次集体亮相.webm
- 时长：32.4 秒，画幅 1080×1920（竖屏）
- 原视频不随仓库分发

```bash
python scripts/watch_video.py --auto "https://commons.wikimedia.org/wiki/File:现场视频_神舟二十三号航天员首次集体亮相.webm" \
  --language zh \
  --credit "中国新闻社《现场视频：神舟二十三号航天员首次集体亮相》，CC BY 4.0，https://creativecommons.org/licenses/by/4.0" \
  --out ./out/shenzhou23
```

也可把自行保存的文件放进 `inbox/`，或用 `--file` 指向本地文件。

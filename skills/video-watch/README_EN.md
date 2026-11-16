# Watch a video, then read the frames

[中文说明](README.md)

**Turn any video into a storyboard an AI agent can actually see — not just a transcript. If the link cannot be downloaded automatically, you get the shortest manual steps.**

Any command-line agent (Claude Code, Codex, Cursor, OpenClaw, Hermes, Gemini CLI, and others) can follow the same commands. When a link cannot be fetched automatically, the tool will not bypass logins. It asks you to pick one simple action instead.

This directory is a release-ready copy. **It has not been pushed to any public repository.**

Use it only to study videos you have the right to watch. The tool does not log in, does not fetch cookies for you, does not read your browser, does not crack signatures or DRM, does not remove watermarks, and does not bundle tools whose purpose is to bypass platform protections.

The code is licensed under [MIT](LICENSE). The sample images are China News Service *Review the wonderful moments of Tianhe core cabin mission in 120 seconds*, licensed **CC BY 3.0** (https://creativecommons.org/licenses/by/3.0 ), with attribution. That media license is separate from the MIT code license; keep the credit if you reuse the sample images.

## Requirements

- A regular computer (**no GPU required**) with Python 3.10+ and [ffmpeg](https://ffmpeg.org/)
- Install dependencies once:

```bash
git clone <repo-url> video-watch
cd video-watch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

The virtualenv does not have to be named `.venv`. Run `python scripts/watch_video.py` in an environment that has the dependencies (`yt-dlp` on PATH, or in the same `bin` directory as `python`).

Optional Bilibili fallback (not vendored in this repo):

```bash
.venv/bin/pip install yutto        # recommended Bilibili fallback, GPL-3.0
# optional: .venv/bin/pip install you-get
```

The first speech-to-text run may download the faster-whisper `base` model (~145 MB) from Hugging Face.

For untruncated Chinese in the reports, install a CJK font such as Noto Sans CJK SC, Source Han Sans, Microsoft YaHei, or PingFang.

Hand `SKILL.md` to any agent, or paste `AGENTS.md` into its system prompt, so every agent follows the same procedure.

## One command

```bash
# once: create the inbox/ folder
python scripts/fetch_help.py --init

# public URL (downloads when possible; otherwise prints steps and JSON)
python scripts/watch_video.py --auto "https://..." --out ./out/run1 --language zh

# you already dropped a video or cookies.txt into inbox/
python scripts/watch_video.py --auto inbox --out ./out/run1 --language zh

# a local file
python scripts/watch_video.py --auto /path/to/clip.mp4 --out ./out/run1 --language zh
```

Preview the manual steps for a URL without downloading:

```bash
python scripts/fetch_help.py --url "https://..."
```

When the run finishes, open `out/run1/report.html` or send `contact_sheet.png` to a vision-capable model. Every run ends with a line `[video-watch-status]` followed by JSON. On failure, relay `user_steps` to the user verbatim (at most three **alternative** options, not three steps to do in sequence).

## Three tiers

| Tier | When | What to do |
|------|------|------------|
| 1 Automatic | The public link can be downloaded (Wikimedia was reliable in our tests; YouTube sometimes works) | Wait for the command, then open the report and contact sheet |
| 2 One user action | The failure is login, cookies, WAF/412/429, or the user already placed a file in inbox/ | Relay `user_steps`. The user picks one option, then says "continue" and you re-run `--auto` |
| 3 Fallback | There is still no video file | Summarize only from titles, comments, or captions the user provides. Say clearly that you cannot see the picture or build a storyboard |

The three tier-2 options (cookies are never suggested as a way to unlock paid/DRM content):

1. **Easiest (recommended):** Follow the platform-specific steps in `user_steps` to save or screen-record the clip, then drop the file into `inbox/`. Ordinary Bilibili posts usually have no "save as mp4" button, so the steps walk through the system recorder (iPhone Control Center, Android quick settings, Win+G, macOS Shift+Command+5). Douyin / Xiaohongshu may offer "save to album" in the share menu.
2. **Or:** On a computer where you are already signed in to the site's **website** (not the phone app), run the `yt-dlp --cookies-from-browser …` command printed for you, and save the file into `inbox/`. **The agent must not run this command or read your browser.**
3. **Or:** Install an official-store open-source extension (Chrome/Edge: Get cookies.txt LOCALLY; Firefox: cookies.txt), export a Netscape `cookies.txt` into `inbox/cookies.txt`, and let the agent retry the URL. Delete the file when you are done. **We have not tested real cookies against Bilibili, Douyin, or Xiaohongshu, and must not claim that they will work.**

See `visuals/tier_flow.png` for the decision flow and `visuals/user_guidance.png` for a guidance sample.

## What actually downloaded in our tests?

The test environment was signed out and had no real cookies. The table below follows tests on 2026-11-11.

| Platform | Drop in a link? | What we observed |
|----------|-----------------|------------------|
| Wikimedia public files (direct or file page) | **Worked in our tests** | Both the Commons file page and `upload.wikimedia.org` direct links produced a full storyboard automatically |
| YouTube public videos | **No guarantee** | The same "Me at the zoo" clip sometimes downloaded and sometimes failed with 429 / bot checks |
| Bilibili | **Did not work while signed out; no guarantee** | A public post returned HTTP 412. The script prints screen-recording steps in Chinese. Real cookies were not tested |
| Douyin | **Did not work while signed out** | Public pages returned 403 and asked for cookies. Save to album or screen-record into `inbox/` |
| Xiaohongshu | **Did not work while signed out** | Requests were redirected to a login page. Save or screen-record into `inbox/` |

See `DOWNLOADERS.md` for the tool comparison and for why some downloaders are not bundled.

## Outputs

- A contact sheet `contact_sheet.png` of every keyframe, so a vision model can read the picture and burned-in captions
- A timeline image `timeline.png`
- A storyboard report (`report.md` / `report.html` / `report.json` / `report_page.png`) plus shot-pacing stats
- A speech transcript next to each shot when recognition works; if it fails, the picture and burned-in captions still stand

Worked examples are in [`examples/`](examples/) (Tianhe 120s and Shenzhou-23 32s), with commands, a report excerpt, and a contact-sheet image. Additional figures are in `visuals/`. Original video files are not shipped in this repository.

## Limitations

OCR misreads text, especially logos. Videos with music and no clear speech may produce an empty transcript — that is why this package puts the picture and burned-in captions first. How well the frames can be understood also depends on whether your model can read the contact sheet. Douyin, Xiaohongshu, and Bilibili in our signed-out tests cannot be promised as "paste a link and watch"; use the short inbox steps instead of asking the script to bypass a login.

## Please do not

Do not log into someone else's account. Do not let the agent fetch cookies from a browser. Do not crack signatures, DRM, or watermarks. Do not call F2, Douyin_TikTok_Download_API, XHS-Downloader, or similar bypass tools. Do not send `cookies.txt` to other people or paste it into a chat. Only analyze videos you have the right to watch.

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在真实 Chrome 里加载交付的 ref-check.html，跑四个网页场景。

必须用浏览器实跑，不能用脚本版替代。结果与截图写在本目录。
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from datetime import datetime, timezone, timedelta
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "ref-check.html"
OUT = Path(__file__).resolve().parent
CHROME = "/usr/bin/google-chrome-stable"

RESNET = (
    "He, K., Zhang, X., Ren, S., & Sun, J. (2016). Deep residual learning "
    "for image recognition. In 2016 IEEE Conference on Computer Vision and "
    "Pattern Recognition (CVPR) (pp. 770–778). "
    "https://doi.org/10.1109/cvpr.2016.90"
)

SCENARIOS = [
    {
        "id": "01_doi_only",
        "title": "仅 DOI（doi.org 链接）",
        "input": "https://doi.org/10.1038/nature16961",
        "intercept": None,
    },
    {
        "id": "02_fake_doi",
        "title": "假 DOI",
        "input": "10.99999/acceptance-fake-doi-does-not-exist-20261111",
        "intercept": None,
    },
    {
        "id": "03_pmid_only",
        "title": "仅 PMID",
        "input": "PMID: 26826612",
        "intercept": None,
    },
    {
        "id": "04_http429",
        "title": "HTTP 429（浏览器请求拦截）",
        "input": RESNET,
        "intercept": "429",
    },
    {
        "id": "05_quoted_title_real_doi",
        "title": "真实文献题名含弯引号+DOI",
        "input": (
            "Bisikalo, D. V., & Cherenkov, A. A. (2016). The influence of coronal mass ejections "
            "on the gas dynamics of the atmosphere of a “hot Jupiter” exoplanet. Astronomy Reports, "
            "60(2), 183-192. https://doi.org/10.1134/s1063772916020013"
        ),
        "intercept": None,
        "expect_status": "已验证",
        "forbid_status": ["疑似编造", "查无此文"],
    },
    {
        "id": "06_title_only_quotes",
        "title": "仅题名含弯引号",
        "input": "Donald Trump’s “Political Incorrectness”: Neoliberalism as Frontstage Racism on Social Media",
        "intercept": None,
        "forbid_status": ["疑似编造"],
    },
    {
        "id": "07_cjk_name_order",
        "title": "中文姓名字序+DOI",
        "input": "佳 李. 分析中医内科治疗胃食管反流病的临床效果[J]. 内科诊疗与进展, 2022, 3(1): 52-54. DOI: 10.37155/2717-5693-0301-22",
        "intercept": None,
        "expect_status": "已验证",
        "forbid_status": ["疑似编造", "查无此文"],
    },
]

API_GLOBS = [
    "https://api.crossref.org/**",
    "https://api.openalex.org/**",
    "https://www.ebi.ac.uk/europepmc/**",
]


def macau_now() -> str:
    tz = timezone(timedelta(hours=8), name="Asia/Macau")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S") + " Asia/Macau（UTC+8）"


def start_server():
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def extract(page) -> dict:
    return page.evaluate(
        """() => {
          const report = document.getElementById("report");
          const card = document.querySelector(".card");
          return {
            statusBar: (document.getElementById("status")||{}).textContent || "",
            runOnclickType: typeof (document.getElementById("run")||{}).onclick,
            pills: [...document.querySelectorAll(".pill")].map(e => e.textContent.trim()),
            cardStatus: card ? (card.querySelector(".status")||{}).textContent : null,
            cardClass: card ? card.className : null,
            raw: card && card.querySelector(".raw") ? card.querySelector(".raw").textContent : null,
            found: card && card.querySelector(".found") ? card.querySelector(".found").innerText : null,
            notes: [...document.querySelectorAll(".notes li")].map(e => e.textContent),
            reportText: report ? report.innerText : "",
          };
        }"""
    )


def run() -> int:
    if not HTML.is_file():
        print("找不到交付文件：", HTML, file=sys.stderr)
        return 2
    if not Path(CHROME).is_file():
        print("找不到系统 Chrome：", CHROME, file=sys.stderr)
        return 2

    httpd = start_server()
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/ref-check.html"
    print("serving", url)

    records = []
    all_ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        for sc in SCENARIOS:
            console_errors = []
            page_errors = []
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
            page = ctx.new_page()
            page.on(
                "console",
                lambda msg, bucket=console_errors: bucket.append(
                    {"type": msg.type, "text": msg.text}
                )
                if msg.type in {"error", "warning"}
                else None,
            )
            page.on("pageerror", lambda exc, bucket=page_errors: bucket.append(str(exc)))

            if sc["intercept"] == "429":
                def fulfill_429(route):
                    route.fulfill(
                        status=429,
                        body="Too Many Requests",
                        headers={
                            "content-type": "text/plain; charset=utf-8",
                            "access-control-allow-origin": "*",
                        },
                    )
                for g in API_GLOBS:
                    page.route(g, fulfill_429)

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#run", timeout=10000)
            onclick_ok = page.evaluate(
                "() => typeof document.getElementById('run').onclick === 'function'"
            )
            if not onclick_ok or page_errors:
                all_ok = False
                shot = OUT / f"{sc['id']}_load_fail.png"
                page.screenshot(path=str(shot), full_page=True)
                rec = {
                    "id": sc["id"],
                    "title": sc["title"],
                    "input": sc["input"],
                    "ok": False,
                    "reason": "页面加载后按钮无 onclick 或出现 JS 异常",
                    "onclick_ok": onclick_ok,
                    "page_errors": page_errors,
                    "console": console_errors,
                    "screenshot": str(shot),
                }
                records.append(rec)
                print("FAIL load", sc["id"], rec["reason"], page_errors)
                ctx.close()
                continue

            page.fill("#input", sc["input"])
            page.click("#run")
            try:
                page.wait_for_function(
                    """() => {
                      const t = (document.getElementById("status")||{}).textContent || "";
                      return t.startsWith("核查完成") || t.startsWith("出错了");
                    }""",
                    timeout=90000,
                )
            except Exception as e:
                all_ok = False
                shot = OUT / f"{sc['id']}.png"
                page.screenshot(path=str(shot), full_page=True)
                rec = {
                    "id": sc["id"],
                    "title": sc["title"],
                    "input": sc["input"],
                    "ok": False,
                    "reason": f"等待结果超时或失败：{type(e).__name__}: {e}",
                    "statusBar": page.evaluate("() => (document.getElementById('status')||{}).textContent"),
                    "page_errors": page_errors,
                    "console": console_errors,
                    "screenshot": str(shot),
                }
                records.append(rec)
                print("FAIL wait", sc["id"], rec["reason"])
                ctx.close()
                continue

            data = extract(page)
            shot = OUT / f"{sc['id']}.png"
            page.screenshot(path=str(shot), full_page=True)
            # 控制台里的 JS 异常 vs 浏览器对 HTTP 404/429 的 “Failed to load resource”
            # 后者不是脚本抛错：getJson 会按 404「无此记录」或 429「请求失败」处理。
            def is_js_error(c):
                text = c.get("text") or ""
                if "Failed to load resource" in text:
                    return False
                return True
            js_errors = [c for c in console_errors if c["type"] == "error" and is_js_error(c)]
            network_console = [c for c in console_errors if c["type"] == "error" and not is_js_error(c)]
            rec = {
                "id": sc["id"],
                "title": sc["title"],
                "input": sc["input"],
                "intercept": sc["intercept"],
                "onclick_ok": onclick_ok,
                "statusBar": data["statusBar"],
                "pills": data["pills"],
                "cardStatus": data["cardStatus"],
                "cardClass": data["cardClass"],
                "raw": data["raw"],
                "found": data["found"],
                "notes": data["notes"],
                "reportText": data["reportText"],
                "page_errors": page_errors,
                "console_errors": js_errors,
                "network_console": network_console,
                "console_warnings": [c for c in console_errors if c["type"] == "warning"],
                "screenshot": str(shot.relative_to(ROOT)),
            }
            rec["ok"] = (not page_errors) and (not js_errors) and data["statusBar"].startswith("核查完成")
            pills = " ".join(data.get("pills") or [])
            card = data.get("cardStatus") or ""
            blob = pills + " " + card
            if sc.get("expect_status") and sc["expect_status"] not in blob:
                rec["ok"] = False
                rec["reason"] = f"期望判定含「{sc['expect_status']}」，实际 pills={data.get('pills')} card={card}"
            forbad = [f for f in (sc.get("forbid_status") or []) if f in blob]
            if forbad:
                rec["ok"] = False
                rec["reason"] = f"不应出现 {forbad}，实际 pills={data.get('pills')} card={card}"
            if not rec["ok"]:
                all_ok = False
            records.append(rec)
            print("=" * 60)
            print(sc["title"], "ok=" + str(rec["ok"]))
            print("statusBar:", data["statusBar"])
            print("pills:", data["pills"])
            print("card:", data["cardStatus"], data["cardClass"])
            print("found:", data["found"])
            print("notes:", data["notes"])
            print("page_errors:", page_errors)
            print("console_errors:", js_errors)
            print("screenshot:", rec["screenshot"])
            ctx.close()
        browser.close()
    httpd.shutdown()

    payload = {
        "when": macau_now(),
        "html": str(HTML),
        "chrome": CHROME,
        "url": url,
        "all_ok": all_ok,
        "scenarios": records,
    }
    # macau_now used %% because of the heredoc... wait, this is a quoted heredoc so %% stays as %%. BUG!
    out = OUT / "results.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out, "all_ok", all_ok)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())

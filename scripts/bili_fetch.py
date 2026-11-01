#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站取源：字幕优先，无字幕则下载音频供语音转写。

用法:
    python bili_fetch.py <url|BV号|av号> [--out DIR] [--page N|--all]
                         [--cookie "SESSDATA=xxx"] [--subs-only] [--audio-only] [--info-only]

产出（默认 --out ./_src）:
    meta.json            视频元信息
    subtitle_pN.srt      字幕（若有）
    subtitle_pN.txt      字幕逐句文本 [mm:ss] 形式
    audio_pN.m4a         音轨（无字幕时）

stdout 打印 KEY=VALUE 行，便于后续脚本/对话解析：
    BVID= / TITLE= / DURATION= / PAGES= / SUBTITLE= / AUDIO= / NOTE=
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
API = "https://api.bilibili.com"


def http(url, referer=None, cookie=None, raw=False, retry=3):
    """带 UA/Referer/Cookie 的请求；412 风控与 403 鉴权失败给出可操作提示。"""
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = "https://www.bilibili.com"
    if cookie:
        headers["Cookie"] = cookie
    last = None
    for attempt in range(retry):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=40) as resp:
                body = resp.read()
            return body if raw else json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 412:
                raise SystemExit(
                    "NOTE=HTTP 412 触发风控。等待 3-10 分钟后重试，或加 --cookie \"SESSDATA=...\"")
            if e.code == 403:
                raise SystemExit(
                    "NOTE=HTTP 403 鉴权失败。音轨地址必须带 Referer；若仍失败通常是会员/付费视频，需 cookie。")
            last = f"HTTP {e.code}"
            time.sleep(1.2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(1.2 * (attempt + 1))
    raise SystemExit(f"NOTE=请求失败 {url} -> {last}")


def parse_target(s):
    """接受完整链接、BV 号或 av 号。"""
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if m:
        return "bvid", m.group(1)
    m = re.search(r"av(\d+)", s, re.I)
    if m:
        return "aid", m.group(1)
    if re.fullmatch(r"\d+", s):
        return "aid", s
    raise SystemExit("NOTE=无法识别 BV/av 号，请直接贴视频链接")


def hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def srt_time(t):
    ms = int(round((t - int(t)) * 1000))
    s = int(t)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d},{ms:03d}"


def save_subtitle(base, body, lang):
    """body: [{'from':0.0,'to':1.2,'content':'...'}] -> .srt + .txt"""
    srt_path = base + ".srt"
    txt_path = base + ".txt"
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, item in enumerate(body, 1):
            f.write(f"{i}\n{srt_time(item['from'])} --> {srt_time(item['to'])}\n"
                    f"{item['content'].strip()}\n\n")
    with open(txt_path, "w", encoding="utf-8") as f:
        for item in body:
            f.write(f"[{hms(item['from'])}] {item['content'].strip()}\n")
    print(f"SUBTITLE_LANG={lang}")
    return srt_path


def pick_subtitle(subs):
    """人工字幕优先于 AI 生成字幕。"""
    if not subs:
        return None
    manual = [s for s in subs if not str(s.get("lan", "")).startswith("ai")]
    return (manual or subs)[0]


def pick_audio(dash):
    """选码率最高的 AAC 音轨；跳过杜比/无损轨（转写用不上，反而更大）。"""
    if not dash:
        return None
    cands = [a for a in dash.get("audio") or [] if str(a.get("codecs", "")).startswith("mp4a")]
    if not cands:
        cands = dash.get("audio") or []
    if not cands:
        return None
    return sorted(cands, key=lambda a: a.get("bandwidth", 0), reverse=True)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="视频链接 / BV 号 / av 号")
    ap.add_argument("--out", default="_src")
    ap.add_argument("--page", type=int, default=1, help="第几个分P，从 1 开始")
    ap.add_argument("--all", action="store_true", help="全部分P")
    ap.add_argument("--cookie", default=os.environ.get("BILI_COOKIE", ""),
                    help='浏览器复制的 Cookie，如 "SESSDATA=xxx"')
    ap.add_argument("--subs-only", action="store_true", help="只取字幕，不下载音频")
    ap.add_argument("--audio-only", action="store_true", help="即使有字幕也下载音频")
    ap.add_argument("--info-only", action="store_true", help="只打印元信息")
    a = ap.parse_args()

    kind, ident = parse_target(a.target)
    query = f"{kind}={ident}" if kind == "bvid" else f"aid={ident}"
    view = http(f"{API}/x/web-interface/view?{query}")
    if view.get("code") != 0:
        raise SystemExit(f"NOTE=取视频信息失败: {view.get('message')}")

    d = view["data"]
    bvid = d["bvid"]
    page_url = f"https://www.bilibili.com/video/{bvid}/"
    pages = d.get("pages") or [{"cid": d["cid"], "part": d["title"], "page": 1}]
    if not a.all:
        idx = max(0, min(a.page - 1, len(pages) - 1))
        pages = [pages[idx]]

    os.makedirs(a.out, exist_ok=True)
    print(f"BVID={bvid}")
    print(f"TITLE={d['title']}")
    print(f"DURATION={d['duration']}")
    print(f"UPLOADER={d.get('owner', {}).get('name', '')}")
    print(f"PUBDATE={time.strftime('%Y-%m-%d', time.localtime(d.get('pubdate', 0)))}")
    print(f"PAGES={len(d.get('pages') or [1])}")

    if a.info_only:
        return

    meta = {
        "bvid": bvid, "aid": d["aid"], "title": d["title"], "duration": d["duration"],
        "uploader": d.get("owner", {}).get("name", ""),
        "pubdate": time.strftime("%Y-%m-%d", time.localtime(d.get("pubdate", 0))),
        "url": page_url, "pages": [],
    }

    for i, pg in enumerate(pages, 1):
        cid = pg["cid"]
        tag = f"p{pg.get('page', i)}"
        entry = {"page": pg.get("page", i), "cid": cid, "part": pg.get("part", ""),
                 "duration": pg.get("duration"), "subtitle": None, "audio": None}

        sub_path = None
        if not a.audio_only:
            player = http(f"{API}/x/player/v2?aid={d['aid']}&cid={cid}", referer=page_url,
                          cookie=a.cookie)
            pdata = player.get("data") or {}
            sub_info = pdata.get("subtitle") or {}
            subs = sub_info.get("subtitles") or []
            chosen = pick_subtitle(subs)
            if chosen:
                url = chosen["subtitle_url"]
                if url.startswith("//"):
                    url = "https:" + url
                body = http(url, referer=page_url, cookie=a.cookie).get("body") or []
                if body:
                    sub_path = save_subtitle(os.path.join(a.out, f"subtitle_{tag}"),
                                             body, chosen.get("lan_doc") or chosen.get("lan"))
                    entry["subtitle"] = sub_path
                    print(f"SUBTITLE={os.path.abspath(sub_path)}")
            elif pdata.get("need_login_subtitle"):
                print("NOTE=该视频有 AI 字幕但需登录，当前未取到。"
                      "若能提供 SESSDATA，用 --cookie 重跑，准确率远高于语音转写。")

        if not sub_path and not a.subs_only:
            play = http(f"{API}/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&fourk=0",
                        referer=page_url, cookie=a.cookie)
            if play.get("code") != 0:
                print(f"NOTE=取播放地址失败: {play.get('message')}（可能需要登录/会员）")
            else:
                audio = pick_audio((play.get("data") or {}).get("dash"))
                if not audio:
                    print("NOTE=未找到 dash 音轨，可能该视频是老式 durl 格式或受版权限制")
                else:
                    out = os.path.join(a.out, f"audio_{tag}.m4a")
                    blob = http(audio["baseUrl"], referer=page_url, cookie=a.cookie, raw=True)
                    with open(out, "wb") as f:
                        f.write(blob)
                    size_mb = len(blob) / 1048576
                    entry["audio"] = out
                    print(f"AUDIO={os.path.abspath(out)}")
                    print(f"AUDIO_MB={size_mb:.1f}")
                    if size_mb < 0.05:
                        print("NOTE=音频体积异常偏小，可能被截断，建议重试")
        meta["pages"].append(entry)

    with open(os.path.join(a.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"META={os.path.abspath(os.path.join(a.out, 'meta.json'))}")
    print("NOTE=下一步：音轨直接交给语音转写工具；音频是 fMP4，后缀 .m4a 即可，无需 ffmpeg")


if __name__ == "__main__":
    main()

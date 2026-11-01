#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把语音转写 / 字幕的原始输出整理成可交付的分段文本。

支持三种输入格式：
    [0:21.900,0:29.750,0] 文本       语音转写服务常见输出（起,止,说话人）
    [00:21] 文本                      字幕脚本输出
    1\\n00:00:21,900 --> 00:00:29,750\\n文本   SRT

用法:
    python format_transcript.py <输入文件> [--out DIR] [--name NAME] [--merge] [--merge-chars 80]

产出:
    <name>_timed.md   带时间戳的分段全文，可直接嵌进交付文档
    <name>_plain.txt  去掉时间戳的连续文本，适合喂给其他模型或人工通读
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BRACKET = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
SRT_TIME = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*")


def parse_ts(tok):
    """'0:21.900' / '00:21' / '01:00:21.5' / '1:02:03' -> 秒"""
    parts = [p for p in tok.strip().split(":") if p != ""]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 1:
        return nums[0]
    return None


def hms(seconds):
    seconds = max(0, int(round(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_srt(text):
    segs = []
    cur = None
    for line in text.splitlines():
        m = SRT_TIME.match(line.strip())
        if m:
            h, mi, s, ms = m.groups()
            cur = {"start": int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000,
                   "speaker": None, "text": ""}
            segs.append(cur)
        elif cur is not None and line.strip() and not line.strip().isdigit():
            cur["text"] = (cur["text"] + " " + line.strip()).strip()
    return [s for s in segs if s["text"]]


def parse_generic(text):
    segs = []
    last_end = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = BRACKET.match(line)
        if m:
            toks = [t.strip() for t in m.group(1).split(",")]
            start = parse_ts(toks[0]) if toks else None
            if start is None:
                continue
            spk = toks[2] if len(toks) > 2 and toks[2].isdigit() else None
            end = parse_ts(toks[1]) if len(toks) > 1 else None
            last_end = end if end is not None else start
            segs.append({"start": start, "speaker": spk, "text": m.group(2).strip()})
        else:
            segs.append({"start": last_end, "speaker": None, "text": line})
    return [s for s in segs if s["text"]]


def merge_segs(segs, limit):
    """把零碎片段合并到一定长度，时间戳取整段的第一句，便于通读。"""
    out = []
    for s in segs:
        if out and len(out[-1]["text"]) < limit and out[-1]["speaker"] == s["speaker"]:
            out[-1]["text"] += s["text"] if _cjk(s["text"][:1]) else " " + s["text"]
        else:
            out.append(dict(s))
    return out


def _cjk(ch):
    return bool(ch) and "\u4e00" <= ch <= "\u9fff"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default=".")
    ap.add_argument("--name", default=None, help="输出文件名前缀，默认取输入文件名")
    ap.add_argument("--merge", action="store_true", help="合并过短的片段，提升可读性")
    ap.add_argument("--merge-chars", type=int, default=80)
    a = ap.parse_args()

    with open(a.input, encoding="utf-8") as f:
        text = f.read()

    segs = parse_srt(text) if SRT_TIME.search(text) else parse_generic(text)
    if not segs:
        raise SystemExit("未解析到任何片段，检查输入格式（需要 [起,止,说话人] 或 SRT）")
    if a.merge:
        segs = merge_segs(segs, a.merge_chars)

    name = a.name or os.path.splitext(os.path.basename(a.input))[0]
    os.makedirs(a.out, exist_ok=True)

    timed = os.path.join(a.out, f"{name}_timed.md")
    with open(timed, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"**[{hms(s['start'])}]** {s['text']}\n\n")

    plain = os.path.join(a.out, f"{name}_plain.txt")
    with open(plain, "w", encoding="utf-8") as f:
        f.write("\n\n".join(s["text"] for s in segs) + "\n")

    chars = sum(len(re.sub(r"\s", "", s["text"])) for s in segs)
    span = segs[-1]["start"] - segs[0]["start"]
    print(f"SEGMENTS={len(segs)}")
    print(f"CHARS={chars}")
    print(f"SPAN={hms(span)}")
    if span > 60:
        print(f"RATE={chars / (span / 60):.0f}字/分钟（中文口播常见 200-320，明显偏低说明有大段静音或转写遗漏）")
    print(f"TIMED={os.path.abspath(timed)}")
    print(f"PLAIN={os.path.abspath(plain)}")
    print(json.dumps({"segments": len(segs), "chars": chars}, ensure_ascii=False))


if __name__ == "__main__":
    main()

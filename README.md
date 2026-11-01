# video-transcript

把视频链接变成可用的文字稿。先取字幕（准确率最高），没有字幕才抓音轨转写，最后做专名校对与结构化交付。

## 用法

在对话里直接给链接即可触发，例如「帮我把这个视频的文字提取出来：<链接>」。

手动执行：

```bash
# B站：字幕优先，无字幕自动下载音轨
python scripts/bili_fetch.py "https://www.bilibili.com/video/BVxxxxxxxxxx/" --out ./_src

# 转写完成后，把带时间戳的原始结果整理成分段文本
python scripts/format_transcript.py ./_src/asr_raw.txt --merge
```

## 目录

```
video-transcript/
├── SKILL.md
├── scripts/
│   ├── bili_fetch.py          # B站取源
│   └── format_transcript.py   # 转写文本格式化
└── references/
    ├── platforms.md           # 各平台分诊表
    ├── asr-proofreading.md    # 校对规则
    └── deliverable-template.md# 交付模板
```

## 依赖

仅需 Python 3 标准库，不需要 ffmpeg / yt-dlp（B站路径）；其他平台另见 `references/platforms.md`。

## 已知边界

- 会员/付费/登录墙内容取不到，需要 cookie
- 抖音、小红书、视频号建议由用户提供本地文件
- 单次转写上限约 1GB / 5 小时
- 转写是语音识别，专名与人名必须校对，规则见 `references/asr-proofreading.md`

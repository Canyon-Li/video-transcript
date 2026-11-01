# 各平台取源分诊表

先判平台，再选路线。**顺序永远是：找字幕 → 取音轨 → 问用户要文件**。

## 快速分诊

| 平台 | 现成字幕 | 取音轨 | 难度 | 说明 |
| --- | --- | --- | --- | --- |
| B站 | 有（AI 字幕需登录） | 公开接口可取 | 低 | 用 `scripts/bili_fetch.py`，已封装全部坑 |
| YouTube | 有（多为自动字幕） | yt-dlp | 低 | 需网络可达；语言参数要显式给 |
| 抖音 | 无 | 直链难稳定 | 中高 | 短链需解析，常需 cookie；建议要本地文件 |
| 快手 | 无 | 同上 | 中高 | 同上 |
| 小红书 | 无 | 需 cookie | 高 | 无公开接口，最稳是录屏 |
| 微信视频号 | 无 | 无公开接口 | 高 | 只能用户本地提供 |
| 播客 RSS | 一般无 | enclosure 直链 | 低 | 直链可直接喂转写工具，不必下载 |
| 本地文件 | — | — | 极低 | 直接进转写 |

## B站

```bash
python scripts/bili_fetch.py "<链接>" --out ./_src
python scripts/bili_fetch.py "<链接>" --subs-only          # 只要字幕
python scripts/bili_fetch.py "<链接>" --all                # 全部分P
python scripts/bili_fetch.py "<链接>" --cookie "SESSDATA=xxx"  # 拿AI字幕/会员内容
```

底层接口（脚本已封装，排障时看这里）：

- 视频信息：`GET api.bilibili.com/x/web-interface/view?bvid=BVxxx`（或 `?aid=`）
- 字幕探测：`GET api.bilibili.com/x/player/v2?aid=&cid=` → `data.subtitle.subtitles[]`，空数组 + `need_login_subtitle: true` 表示有字幕但需登录
- 播放地址：`GET api.bilibili.com/x/player/playurl?bvid=&cid=&fnval=16&fourk=0` → `data.dash.audio[]`，按 bandwidth 降序取 AAC 轨
- 下载音轨：**必须带 `Referer: https://www.bilibili.com/video/BVxxx/`**，否则 403

已知坑：

- 412 = 风控。等 3–10 分钟，或带 cookie，不要连续重试。
- 老视频可能只有 `durl`（整段 mp4）没有 `dash`，此时取 `durl[0].url` 同样带 Referer 下载。
- 多分P 的 `cid` 不同，字幕和音轨都要按 cid 分别取。
- 字幕 `subtitle_url` 常以 `//` 开头，补 `https:`。

## YouTube

```bash
yt-dlp --write-subs --write-auto-subs --sub-langs "zh-Hans,zh,en" \
       --skip-download -o "%(id)s.%(ext)s" "<url>"
yt-dlp -f bestaudio -o "%(id)s.%(ext)s" "<url>"
```

注意：自动字幕未经标点与断句处理，直接当正文读会很难看，仍需第 5 步整理。

## 抖音 / 快手 / 小红书

不要在这类平台上耗时间。标准话术：请用户把视频下载到本地（或用系统录屏），把文件路径给我。

若必须尝试：`yt-dlp` 偶尔可用，但成功率随平台改版波动；带浏览器 cookie 能提高成功率。**试一次不成就转人工路径**，不要反复换参数。

## 播客 / 音频直链

RSS 的 `<enclosure url="...mp3">` 通常是无需鉴权的直链，可直接作为转写工具的输入路径，省掉下载步骤。若有防盗链，先下载再传。

## 本地文件

直接用。注意两点：

- 视频文件无需先抽音频，转写工具能直接吃 mp4；只有超限才考虑切分。
- 文件名含中文/空格时用引号包裹，Windows 下不要用 `.bat`/`.ps1` 传非 ASCII 路径（会乱码）。

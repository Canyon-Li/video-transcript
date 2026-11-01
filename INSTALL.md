# 安装说明

这份文件是给**agent**读的。用户如果说「安装这个技能」并给了仓库地址，照本文执行即可，不需要读完 `README.md`。

---

## 0. 先确认三件事

| 项 | 取值 |
| --- | --- |
| 技能目录 | WorkBuddy：`~/.workbuddy/skills`　Claude Code：`~/.claude/skills` |
| 安装位置 | `<技能目录>/video-transcript` |
| 依赖 | 无。Python 3 标准库即可，不需要 ffmpeg / yt-dlp |

判断该往哪装：看用户当前用的客户端。不确定就选 `~/.workbuddy/skills`，不存在则创建。

---

## 1. 安装（一条命令）

```bash
git clone --depth 1 https://github.com/Canyon-Li/video-transcript.git "<技能目录>/video-transcript"
```

**不要**用 `--recurse-submodules`（没有子模块），也**不要**先 `cd` 进技能目录再决定——路径写全，避免装到错误位置。

---

## 2. 验证（必做，不要跳过）

```bash
python "<技能目录>/video-transcript/scripts/install.py" --check --json
```

期望最后一行 JSON 里 `"ok": true`，且 `action` 为 `check`。为 `false` 时按输出里的 `errors` 处理，不要向用户汇报「已安装」。

这个检查做三件事：目录是否可达、`SKILL.md` 的 frontmatter 能否解析、两个核心脚本是否在位。它还会顺手修掉 `\---` 这种被格式化工具体坏的首行。

---

## 3. 生效

技能列表在**会话启动时**扫描。新装的技能在当前会话里通常不可见，需要用户重开会话。

汇报时请明确说明这一点，不要说「现在就能用」。

---

## 其他情形

### 用户已有本地 clone，想保持仓库独立

```bash
python "<本地仓库>/scripts/install.py" --link "<本地仓库路径>" --json
```

会用目录联接（Windows junction / POSIX symlink）接进技能目录。仓库放在别处（例如 `D:\git\...`）时用这个，`--update` 之后无需重新安装。

### 更新 / 卸载

```bash
python "<技能目录>/video-transcript/scripts/install.py" --update --json     # git pull
python "<技能目录>/video-transcript/scripts/install.py" --uninstall         # 只摘链接，不删仓库
```

### 没有 git

```bash
python scripts/install.py --json      # 自动降级为下载 zip
```

### 重复安装

`install.py` 是幂等的：已装好会返回 `"action": "already-installed"` 且 `"ok": true`。目标存在但损坏时才会报错，此时先 `--uninstall`。

---

## 给用户的话术（可直接复用）

> 已安装到 `<技能目录>/video-transcript`，自检通过。**需要重开一次会话**才能被识别，之后直接把视频链接丢给我就行。

若自检失败：

> 装是装上了，但自检没通过：`<errors 原文>`。我把问题定位在这里，暂时别用。

---

## 边界

- 不要为了「让它跑起来」去装 ffmpeg、yt-dlp 或任何 ASR 依赖——B 站路径用不到，转写另行处理。
- 不要修改仓库里的 `SKILL.md`、`scripts/` 来「适配」本机环境。装不上就报告，不要改源码。
- 不涉及登录态、密钥、cookie 的读写。

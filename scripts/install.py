#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video-transcript 技能安装器。

只用标准库，Win/macOS/Linux 通用。给 agent 用的时候建议加 --json，
拿到结构化结果再决定怎么向用户汇报。

常用：
    python scripts/install.py                    # 克隆到技能目录
    python scripts/install.py --link D:\\git\\video-transcript
    python scripts/install.py --check            # 只体检，不改动
    python scripts/install.py --update
    python scripts/install.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

SKILL_NAME = "video-transcript"
DEFAULT_REPO = "https://github.com/Canyon-Li/video-transcript"
BRANCH = "main"

# 技能根目录候选：(显示名, 路径)。按顺序取第一个已存在的；
# 都不存在时用第一个（WorkBuddy）并自动创建。
SKILL_ROOTS = [
    ("WorkBuddy", Path.home() / ".workbuddy" / "skills"),
    ("Claude Code", Path.home() / ".claude" / "skills"),
]

RESULT: dict = {"ok": False, "action": None, "skill_dir": None, "messages": [], "warnings": []}


def say(msg: str = "") -> None:
    print(msg)
    if msg:
        RESULT["messages"].append(msg)


def warn(msg: str) -> None:
    print("WARN: " + msg)
    RESULT["warnings"].append(msg)


# ---------------------------------------------------------------- 路径与链接


def link_target(p: Path):
    """返回符号链接/目录联接指向的目标；普通目录返回 None。

    注意：Windows 的 Directory Junction 在 Python 里 os.path.islink() 和
    Path.is_symlink() 都返回 False，只有 os.readlink() 能读出来。
    """
    try:
        return os.readlink(str(p))
    except (OSError, ValueError):
        return None


def is_link(p: Path) -> bool:
    return link_target(p) is not None


def pick_skills_dir(explicit: str | None) -> tuple[Path, str]:
    if explicit:
        return Path(explicit).expanduser().resolve(), "命令行指定"
    for label, root in SKILL_ROOTS:
        if root.is_dir():
            return root, label
    return SKILL_ROOTS[0][1], SKILL_ROOTS[0][0] + "（新建）"


def make_link(target: Path, link: Path) -> str:
    """把 target 接到 link。返回实际方式：junction / symlink / copy。"""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or is_link(link):
        raise SystemExit(f"目标已存在，先卸载或换 --skills-dir：{link}")

    if os.name == "nt":
        # 目录联接优先：不需要管理员权限；symlink 需要开发者模式
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, encoding="mbcs", errors="replace",
        )
        if r.returncode == 0 and link.exists():
            return "junction"
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
            return "symlink"
        except OSError:
            pass
    else:
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
            return "symlink"
        except OSError as e:
            warn(f"符号链接创建失败（{e}），改为复制")

    shutil.copytree(str(target), str(link), ignore=shutil.ignore_patterns(".git"))
    return "copy"


def remove_link(link: Path) -> None:
    """只摘链接本身，绝不触碰它指向的真实目录。"""
    if not is_link(link):
        raise SystemExit(
            f"拒绝操作：{link} 不是链接，是真实目录。\n"
            f"确认要删掉整份安装，请手动删除，或加 --force-real-dir。"
        )
    for fn in (os.rmdir, os.unlink):
        try:
            fn(str(link))
            return
        except OSError:
            continue
    raise SystemExit(f"删除链接失败：{link}")


# ---------------------------------------------------------------- 内容校验


def check_frontmatter(skill_dir: Path) -> dict:
    """校验 SKILL.md 的 frontmatter，顺手修掉 `\\---` 这种被格式化工具体坏的写法。"""
    info = {"path": None, "name": None, "description": False, "repaired": False, "errors": []}
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        info["errors"].append("缺少 SKILL.md")
        return info
    info["path"] = str(md)

    text = md.read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[0].strip() in ("\\---", "\\---  "):
        # 被 Markdown 格式化工具转义过，frontmatter 会解析失败
        for i, ln in enumerate(lines):
            if ln.strip().startswith("\\---") and i < 8:
                lines[i] = "---"
        md.write_text("\n".join(lines), encoding="utf-8")
        text = "\n".join(lines)
        info["repaired"] = True
        warn("SKILL.md 首行被转义成 `\\---`，已自动修正")

    if not text.startswith("---"):
        info["errors"].append("frontmatter 缺失或首行不是 ---")
        return info
    end = text.find("\n---", 3)
    if end < 0:
        info["errors"].append("frontmatter 未闭合")
        return info

    block = text[3:end]
    for ln in block.split("\n"):
        if ln.startswith("name:"):
            info["name"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("description:"):
            info["description"] = len(ln.split(":", 1)[1].strip()) > 10
    if not info["name"]:
        info["errors"].append("frontmatter 缺 name")
    elif info["name"] != SKILL_NAME:
        info["errors"].append(f"name 是 {info['name']}，应为 {SKILL_NAME}")
    if not info["description"]:
        info["errors"].append("frontmatter 缺 description 或过短")
    return info


def inspect(skill_dir: Path) -> dict:
    rep = {
        "skill_dir": str(skill_dir),
        "exists": skill_dir.exists(),
        "is_link": is_link(skill_dir),
        "link_target": link_target(skill_dir),
        "frontmatter": None,
        "scripts": {},
    }
    if not rep["exists"]:
        return rep
    rep["frontmatter"] = check_frontmatter(skill_dir)
    for s in ("bili_fetch.py", "format_transcript.py"):
        rep["scripts"][s] = (skill_dir / "scripts" / s).is_file()
    return rep


# ---------------------------------------------------------------- 安装动作


def git(src: str, dest: Path) -> bool:
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", BRANCH, src, str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        warn(f"git clone 失败：{(r.stderr or '').strip()[:300]}")
        return False
    return True


def zip_download(src: str, dest: Path) -> bool:
    """没有 git 时的兜底：下 zip 解压。"""
    base = src.rstrip("/").removesuffix(".git")
    url = f"{base.replace('https://github.com/', 'https://codeload.github.com/')}/zip/refs/heads/{BRANCH}"
    say(f"git 不可用，改用 zip 下载：{url}")
    try:
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "repo.zip"
            urllib.request.urlretrieve(url, zpath)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(td)
            roots = [p for p in Path(td).iterdir() if p.is_dir()]
            if len(roots) != 1:
                warn("zip 结构异常，找不到唯一的顶层目录")
                return False
            shutil.copytree(str(roots[0]), str(dest))
        return True
    except Exception as e:
        warn(f"zip 下载失败：{e}")
        return False


def fetch(src: str, dest: Path) -> None:
    if dest.exists() or is_link(dest):
        raise SystemExit(f"目标已存在：{dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("git") and git(src, dest):
        return
    if zip_download(src, dest):
        return
    raise SystemExit("取源失败：git 和 zip 都没成功。检查网络或改用 --link 指定本地路径。")


def report(rep: dict) -> bool:
    fm = rep["frontmatter"] or {}
    scripts_ok = bool(rep["scripts"]) and all(rep["scripts"].values())
    ok = bool(rep["exists"] and fm and not fm.get("errors") and scripts_ok)
    print()
    print(f"  技能目录   {rep['skill_dir']}")
    if rep["is_link"]:
        print(f"  安装方式   目录联接 → {rep['link_target']}")
    elif rep["exists"]:
        print("  安装方式   实体目录（git clone 或复制）")
    print(f"  SKILL.md   {'OK' if fm else '缺失'}"
          + (f"  name={fm.get('name')}" if fm and fm.get("name") else ""))
    for s, present in (rep["scripts"] or {}).items():
        print(f"  {s:<22}{'OK' if present else '缺失'}")
    for e in (fm or {}).get("errors", []):
        print(f"  错误：{e}")
    print()
    print("  状态：" + ("可用" if ok else "不可用"))
    return ok


def cmd_install(args) -> None:
    skills_dir, label = pick_skills_dir(args.skills_dir)
    dest = skills_dir / SKILL_NAME
    RESULT["skill_dir"] = str(dest)
    print(f"技能目录：{skills_dir}  （{label}）")

    # 幂等：已装好就直接报可用，agent 重跑不会失败
    if dest.exists() or is_link(dest):
        rep = inspect(dest)
        fm = rep["frontmatter"] or {}
        if fm and not fm.get("errors"):
            RESULT["action"] = "already-installed"
            say("已安装，跳过（要更新用 --update，要重装先 --uninstall）")
            RESULT["ok"] = report(rep)
            return
        raise SystemExit(
            f"目标已存在但不可用：{dest}\n"
            f"先 --uninstall 摘掉再重装。"
        )

    if args.link:
        target = Path(args.link).expanduser().resolve()
        if not (target / "SKILL.md").is_file():
            raise SystemExit(f"{target} 里没有 SKILL.md，看起来不是这个技能仓库")
        mode = make_link(target, dest)
        RESULT["action"] = f"link:{mode}"
        say(f"已用 {mode} 把 {target} 接到 {dest}")
    else:
        fetch(args.repo, dest)
        RESULT["action"] = "clone"
        say(f"已克隆 {args.repo} → {dest}")

    RESULT["ok"] = report(inspect(dest))
    if not RESULT["ok"]:
        raise SystemExit(1)


def cmd_check(args) -> None:
    skills_dir, label = pick_skills_dir(args.skills_dir)
    dest = Path(args.skills_dir).expanduser() / SKILL_NAME if args.skills_dir else skills_dir / SKILL_NAME
    RESULT["skill_dir"] = str(dest)
    rep = inspect(dest)
    RESULT["action"] = "check"
    RESULT["ok"] = report(rep)
    if not RESULT["ok"]:
        raise SystemExit(1)


def cmd_update(args) -> None:
    skills_dir, _ = pick_skills_dir(args.skills_dir)
    dest = skills_dir / SKILL_NAME
    RESULT["skill_dir"] = str(dest)
    real = Path(link_target(dest)) if is_link(dest) else dest
    if not (real / ".git").is_dir():
        raise SystemExit(f"{real} 不是 git 仓库，无法更新；请卸载后重装")
    r = subprocess.run(["git", "-C", str(real), "pull", "--ff-only"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"更新失败：{(r.stderr or '').strip()[:300]}")
    RESULT["action"] = "update"
    say((r.stdout or "").strip()[:500] or "已是最新")
    RESULT["ok"] = report(inspect(dest))


def cmd_uninstall(args) -> None:
    skills_dir, _ = pick_skills_dir(args.skills_dir)
    dest = skills_dir / SKILL_NAME
    RESULT["skill_dir"] = str(dest)
    if not dest.exists() and not is_link(dest):
        RESULT["action"] = "uninstall"
        RESULT["ok"] = True
        say(f"本来就未安装：{dest}")
        return
    if is_link(dest):
        tgt = link_target(dest)
        remove_link(dest)
        say(f"已摘除链接 {dest}（目标 {tgt} 未改动）")
    else:
        if not args.force_real_dir:
            raise SystemExit(
                f"{dest} 是实体目录，删除会丢掉里面的内容。\n"
                f"确认后加 --force-real-dir 重试。"
            )
        shutil.rmtree(str(dest))
        say(f"已删除实体目录 {dest}")
    RESULT["action"] = "uninstall"
    RESULT["ok"] = True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="安装 video-transcript 技能到 agent 的技能目录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("常用：")[-1],
    )
    ap.add_argument("--skills-dir", help="技能根目录，默认自动探测 ~/.workbuddy/skills 或 ~/.claude/skills")
    ap.add_argument("--link", metavar="本地仓库路径", help="用目录联接接入已有 clone，不复制")
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"仓库地址，默认 {DEFAULT_REPO}")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="只体检，不改动任何文件")
    g.add_argument("--update", action="store_true", help="git pull 更新已安装的技能")
    g.add_argument("--uninstall", action="store_true", help="卸载（只摘链接，不删目标仓库）")
    ap.add_argument("--force-real-dir", action="store_true", help="卸载时允许删除实体目录（危险）")
    ap.add_argument("--json", action="store_true", help="输出 JSON，便于 agent 解析")
    args = ap.parse_args()

    try:
        if args.check:
            cmd_check(args)
        elif args.update:
            cmd_update(args)
        elif args.uninstall:
            cmd_uninstall(args)
        else:
            cmd_install(args)
    finally:
        if args.json:
            print(json.dumps(RESULT, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

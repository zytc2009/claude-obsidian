#!/usr/bin/env python3
"""
sync_workbuddy.py — 把 repo 里的 obsidian skill 同步到 WorkBuddy / 打包市场上架包。

用法:
  python3 sync_workbuddy.py            # 本地安装到 ~/.workbuddy/skills/obsidian（注入本机真实路径）
  python3 sync_workbuddy.py --pack     # 生成可上架技能市场的便携 zip 包（dist/obsidian-skill.zip）
  python3 sync_workbuddy.py --dry-run  # 只打印将要做的改动

三种分发形态共用一个真相源（repo 的 skills/obsidian/SKILL.md，面向 Claude/Codex）：
  - 本地 WorkBuddy：注入本机 vault 路径与 skill 目录，命令可直接复制执行
  - 市场包：占位符版 SKILL.md（不写死任何个人路径/绝对路径），供他人安装到自己的环境

适配点（Claude/Codex -> WorkBuddy）:
  1. skill 目录查找顺序加入 ~/.workbuddy/skills/obsidian
  2. python -> python3（macOS 无 python 别名时兜底）
  3. 去掉 /obsidian slash-command 依赖，改为中文自然语言触发（WorkBuddy 无 slash 命令）
  4. vault 路径处理：本地版注入真实绝对路径；市场版保留 $OBSIDIAN_VAULT_PATH 并提示询问用户
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_SKILL = REPO_ROOT / "skills" / "obsidian"
WB_SKILL_DIR = Path.home() / ".workbuddy" / "skills" / "obsidian"
DIST_DIR = REPO_ROOT / "dist" / "obsidian-skill"
DIST_ZIP = REPO_ROOT / "dist" / "obsidian-skill.zip"

# 本地安装时使用的 vault 路径：优先沿用 shell 里已配好的环境变量，否则用当前机器上探测到的位置
LOCAL_VAULT = os.environ.get("OBSIDIAN_VAULT_PATH") or "/Users/Admin/whb/AI/AI_stdudy/obsidian"

# WorkBuddy 平台没有 slash command，description 必须靠自然语言命中（不含尖括号，符合上架硬规则）
WB_DESCRIPTION = (
    "管理本地 Obsidian 知识库（vault）。当用户想记东西、查知识库、整理笔记时触发："
    "「记一下」「随手记」「闪念」「想到一个」，「抓取这个网页/链接」「保存这篇文章」「归档这个链接」，"
    "「整理这次对话」「把我们的讨论存下来」「把这段对话写成笔记」，"
    "「我笔记里有没有…」「在我笔记里查一下…」「知识库里关于…的内容」，"
    "「写篇笔记/概念卡/主题页/项目笔记」「整理归档相关笔记」「检查知识库健康度」「断链/孤立笔记」，"
    "「知识图谱」「笔记关系图」「重建索引」「找孤儿笔记」「记忆状态」。"
    "也支持微信公众号、小红书、B站、YouTube 链接抓取，以及把知识库内容写成文章。"
    "注意：这是本地 vault 的读写，不是云端文档。"
)

# 市场上架强制字段（display 展示名 + 中英文描述），缺失会被审核打回
WB_DISPLAY_NAME = "Obsidian 知识库助手"
WB_DISPLAY_NAME_EN = "Obsidian Knowledge Base Assistant"
WB_DESC_ZH = (
    "在本地 Obsidian 知识库（vault）中读写笔记：闪念速记、网页/文件抓取、对话归档、"
    "概念卡/主题页/项目笔记写作、双向链接校验与知识图谱可视化。零第三方依赖，纯本地运行。"
)
WB_DESC_EN = (
    "Read and write notes in a local Obsidian vault: quick capture, web/file clipping, "
    "conversation logging, concept/topic/project note authoring, wikilink linting and "
    "knowledge-graph visualization. Zero third-party dependencies, fully local."
)

WB_HEADER = """---
name: obsidian-vault-manager
version: 1.0.0
display_name: {display_name}
display_name_en: {display_name_en}
description: "{description}"
description_zh: "{description_zh}"
description_en: "{description_en}"
agent_created: true
---

# Obsidian 知识库管理（WorkBuddy 版）

You are managing the user's local Obsidian vault at `{vault}`.

## 0. 环境自检（每次被调用先做一次）

本 skill 的脚本与本文（SKILL.md）同目录，解析顺序：

1. 当前 skill 文件所在目录 → **`{skill_dir}`**（WorkBuddy 安装位置，默认命中）
2. 环境变量 `OBSIDIAN_SKILL_DIR`
3. 开发仓库：`{repo}/skills/obsidian`
4. Codex 安装目录：`~/.codex/skills/obsidian`

**vault 路径**：`{vault}`。若 shell 里没有 `OBSIDIAN_VAULT_PATH`，
脚本命令里显式带 `--vault "{vault}"`，不要依赖 `~/obsidian` 这种写法——Python 不展开 `~`。

**Python**：统一用 `python3`（macOS 上 `python` 可能不存在）。

## 0.5 WorkBuddy 专属增强

| 能力 | 说明 |
|---|---|
| **图谱可视化** | `--type graph` 生成单文件 HTML 后，用 present_files 打开给用户看（WorkBuddy 能直接预览 HTML，Claude Code 不行） |
| **定时任务** | 可为用户创建自动化：每周 lint 健康检查、每日 index 重建 |
| **对话沉淀** | WorkBuddy 会话结束前可提议 `log` 模式，把本次调研/讨论落成笔记 |
| **文件直达** | 生成的笔记/图谱路径可直接 present_files 给用户 |

## 触发方式（无 slash 命令）

WorkBuddy 没有 `/obsidian` 命令，全部靠自然语言识别。见第 1 节的意图表。

---

"""

# 市场包版 header：不写死任何个人路径/绝对路径，符合上架审核要求
PORTABLE_HEADER = """---
name: obsidian-vault-manager
version: 1.0.0
display_name: {display_name}
display_name_en: {display_name_en}
description: "{description}"
description_zh: "{description_zh}"
description_en: "{description_en}"
agent_created: true
---

# Obsidian 知识库管理（WorkBuddy 技能版）

You are managing the user's local Obsidian vault.

## 0. 确定 vault 路径（每次先确认）

- 先读环境变量 `OBSIDIAN_VAULT_PATH`。
- 若未设置，**直接询问用户**其 Obsidian vault 的根目录（不要假设 `~/obsidian` 一定存在——Python 不展开 `~`）。
- 之后所有命令通过 `--vault "<用户提供的 vault 路径>"` 传路径。

## 0.5 确定脚本位置

- 所有脚本（`obsidian_writer.py`、`memory_manager.py`、`profile_manager.py`、`vault_doctor.py`、`importers/`）与本文（SKILL.md）**同目录**。
- **运行前先 `cd` 到本 skill 目录**（WorkBuddy 安装后通常是 `~/.workbuddy/skills/obsidian`），之后命令统一用 `python3 obsidian_writer.py ...`，无需写死绝对路径。

## 0.6 触发方式（无 slash 命令）

WorkBuddy 没有 `/obsidian` 命令，全部靠自然语言识别。见第 1 节的意图表。

## WorkBuddy 专属增强

| 能力 | 说明 |
|---|---|
| **图谱可视化** | `--type graph` 生成单文件 HTML，可用 present_files 打开给用户看 |
| **定时任务** | 可为用户创建自动化：每周 lint 健康检查、每日 index 重建 |
| **对话沉淀** | 会话结束前可提议 `log` 模式，把调研/讨论落成笔记 |
| **文件直达** | 生成的笔记/图谱路径可直接 present_files 给用户 |

---

"""


def _yq(s: str) -> str:
    """把字符串安全地包进 YAML 双引号：转义反斜杠与双引号，避免破坏 frontmatter 解析。"""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_skill_md(src_text: str, vault: str, skill_dir: str, portable: bool = False) -> str:
    text = src_text

    # 1. 去掉原 frontmatter（description 由 WorkBuddy 版重写）
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :].lstrip("\n")

    # 2. 丢弃原版「Skill 路径兼容」及其之前的残留——WorkBuddy 版 header 已给出路径规则。
    #    从「## 会话启动」开始保留（记忆注入逻辑仍需沿用）。
    for anchor in ("## 会话启动", "## Step 1: Detect Operation Mode"):
        idx = text.find(anchor)
        if idx != -1:
            text = text[idx:]
            break

    # 3. python -> python3
    text = text.replace("python <OBSIDIAN_SKILL_DIR>/", "python3 <OBSIDIAN_SKILL_DIR>/")
    text = text.replace("python skills/obsidian/", "python3 <OBSIDIAN_SKILL_DIR>/")

    # 4. slash 命令 -> 自然语言（WorkBuddy 没有 slash command）
    text = re.sub(r"`/obsidian[^`]*`\s*或\s*", "", text)
    text = re.sub(r"`/obsidian[^`]*`", "", text)
    text = text.replace("Triggered by /obsidian, or natural language like", "Triggered by natural language like")

    # 5. vault 路径占位符
    if portable:
        # 市场包：保留环境变量，未设置则询问用户
        text = text.replace('${OBSIDIAN_VAULT_PATH:-~/obsidian}', "$OBSIDIAN_VAULT_PATH")
    else:
        # 本地：注入真实绝对路径（命令可直接复制执行）
        text = text.replace("${OBSIDIAN_VAULT_PATH:-~/obsidian}", vault)
        text = text.replace("默认路径是 `~/obsidian/`", f"默认路径是 `{vault}`")
        text = text.replace("The default path is `~/obsidian/`", f"The default path is `{vault}`")

    # 6. skill 目录占位符
    if portable:
        # 市场包：去掉目录前缀，命令改为相对路径（配合“先 cd 到 skill 目录”的约定）
        text = text.replace("<OBSIDIAN_SKILL_DIR>/", "")
    else:
        # 本地：替换为真实绝对路径
        text = text.replace("<OBSIDIAN_SKILL_DIR>", str(skill_dir))

    header = (PORTABLE_HEADER if portable else WB_HEADER).format(
        description=_yq(WB_DESCRIPTION),
        display_name=WB_DISPLAY_NAME,
        display_name_en=WB_DISPLAY_NAME_EN,
        description_zh=_yq(WB_DESC_ZH),
        description_en=_yq(WB_DESC_EN),
        vault=vault,
        skill_dir=skill_dir,
        repo=REPO_ROOT,
    )
    return header + text


def sync_local():
    """本地安装到 ~/.workbuddy/skills/obsidian（注入本机真实路径）"""
    if not SRC_SKILL.exists():
        print(f"[ERR] 源目录不存在: {SRC_SKILL}")
        return 1

    WB_SKILL_DIR.mkdir(parents=True, exist_ok=True)
    changed = []
    for src_file in SRC_SKILL.rglob("*"):
        if src_file.is_dir():
            continue
        if "__pycache__" in src_file.parts or src_file.suffix == ".pyc":
            continue
        rel = src_file.relative_to(SRC_SKILL)
        if rel.name == "SKILL.md":
            continue
        dst = WB_SKILL_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if (not dst.exists()) or (src_file.read_bytes() != dst.read_bytes()):
            shutil.copy2(src_file, dst)
            changed.append(str(rel))

    src_md = (SRC_SKILL / "SKILL.md").read_text(encoding="utf-8")
    out_md = build_skill_md(src_md, LOCAL_VAULT, str(WB_SKILL_DIR), portable=False)
    (WB_SKILL_DIR / "SKILL.md").write_text(out_md, encoding="utf-8")
    changed.append("SKILL.md (WorkBuddy 本地适配版)")

    print(f"[OK] WorkBuddy skill -> {WB_SKILL_DIR}")
    print(f"[OK] vault -> {LOCAL_VAULT}")
    for c in changed:
        print(f"  ~ {c}")
    if not changed:
        print("  (无变化)")
    return 0


def pack_marketplace():
    """生成可上架技能市场的便携 zip 包（dist/obsidian-skill.zip）"""
    if not SRC_SKILL.exists():
        print(f"[ERR] 源目录不存在: {SRC_SKILL}")
        return 1

    # 清理旧的构建目录
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 复制所有脚本（排除 __pycache__ / .pyc / SKILL.md）
    copied = []
    for src_file in SRC_SKILL.rglob("*"):
        if src_file.is_dir():
            continue
        if "__pycache__" in src_file.parts or src_file.suffix == ".pyc":
            continue
        if src_file.name == "SKILL.md":
            continue
        rel = src_file.relative_to(SRC_SKILL)
        dst = DIST_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        copied.append(str(rel))

    # 生成便携版 SKILL.md（占位符，无个人路径）
    src_md = (SRC_SKILL / "SKILL.md").read_text(encoding="utf-8")
    out_md = build_skill_md(src_md, "$OBSIDIAN_VAULT_PATH（未设置则询问用户）", "<本 skill 目录>", portable=True)
    (DIST_DIR / "SKILL.md").write_text(out_md, encoding="utf-8")

    # 校验：不得出现个人绝对路径 / 尖括号占位符
    bad = []
    full = (DIST_DIR / "SKILL.md").read_text(encoding="utf-8")
    if "/Users/Admin" in full:
        bad.append("发现个人绝对路径 /Users/Admin")
    if "<OBSIDIAN_SKILL_DIR>" in full:
        bad.append("发现尖括号占位符 <OBSIDIAN_SKILL_DIR>")
    if any("/Users/Admin" in p.read_text(encoding="utf-8", errors="ignore") for p in DIST_DIR.rglob("*.py")):
        bad.append("脚本里出现个人绝对路径")

    # frontmatter 上架必填字段校验（缺一个都会被审核打回）
    required_keys = [
        "version:",
        "display_name:",
        "display_name_en:",
        "description_zh:",
        "description_en:",
    ]
    fm = full.split("\n---", 1)[0]  # 仅取第一个 --- 之前的 frontmatter
    for key in required_keys:
        if key not in fm:
            bad.append(f"frontmatter 缺少必填字段 {key}")
    if bad:
        print("[ERR] 市场包校验失败：")
        for b in bad:
            print(f"  - {b}")
        return 1

    # 打成 zip（SKILL.md + 脚本）
    if DIST_ZIP.exists():
        DIST_ZIP.unlink()
    with zipfile.ZipFile(DIST_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(DIST_DIR.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(DIST_DIR))

    print(f"[OK] 市场包 -> {DIST_ZIP}")
    print(f"[OK] 包含 {len(copied)} 个脚本文件 + 便携版 SKILL.md")
    print(f"[OK] 校验通过：无个人绝对路径 / 无尖括号占位符")
    print()
    print("下一步：登录 https://open.workbuddy.cn → 发布管理 → 新建技能 → 上传此 zip → 提交审核")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", action="store_true", help="生成可上架技能市场的便携 zip 包")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做的改动")
    args = ap.parse_args()

    if args.dry_run:
        print(f"[dry-run] 本地安装目标: {WB_SKILL_DIR}")
        print(f"[dry-run] vault: {LOCAL_VAULT}")
        return 0

    if args.pack:
        return pack_marketplace()

    return sync_local()


if __name__ == "__main__":
    sys.exit(main())

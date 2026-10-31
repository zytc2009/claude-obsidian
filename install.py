"""
install.py — 安装 obsidian skill 到不同 AI 助手环境。

用法:
  python install.py                      # 默认安装到 Claude Code (~/.claude)
  python install.py --target workbuddy   # 安装到 WorkBuddy（自动适配，注入本机路径）
  python install.py --target codex       # 安装到 Codex (~/.codex)
  python install.py --target all         # 三个环境都装

说明:
  - Claude Code / Codex: 直接复制 repo 的 skills/obsidian（含 slash 命令，面向这两类环境）
  - WorkBuddy: 调用 sync_workbuddy.py 生成适配版（自然语言触发、python3、注入本机 vault 路径）
  - 设置 OBSIDIAN_VAULT_PATH 环境变量可覆盖默认 vault 路径
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
CLAUDE_DIR = Path.home() / ".claude"
CODEX_DIR = Path.home() / ".codex"
SRC_SKILL = REPO_ROOT / "skills" / "obsidian"
SYNC_SCRIPT = REPO_ROOT / "sync_workbuddy.py"


def install_claude():
    print("Installing to Claude Code (~/.claude)...")
    skills_dir = CLAUDE_DIR / "skills"
    scripts_dir = CLAUDE_DIR / "scripts"
    skills_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    skill_target = skills_dir / "obsidian"
    if skill_target.exists():
        shutil.rmtree(skill_target)
    shutil.copytree(SRC_SKILL, skill_target)

    shutil.copy(skill_target / "obsidian_writer.py", scripts_dir / "obsidian_writer.py")
    print(f"  [OK] Skill   -> {skill_target / 'SKILL.md'}")
    print(f"  [OK] Script  -> {scripts_dir / 'obsidian_writer.py'}")
    print("\nDone. Use /obsidian in any Claude Code session.")
    print("Set OBSIDIAN_VAULT_PATH env var to override the default vault path.\n")


def install_codex():
    print("Installing to Codex (~/.codex)...")
    skills_dir = CODEX_DIR / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_target = skills_dir / "obsidian"
    if skill_target.exists():
        shutil.rmtree(skill_target)
    shutil.copytree(SRC_SKILL, skill_target)
    print(f"  [OK] Skill   -> {skill_target / 'SKILL.md'}")
    print("\nDone. Use /obsidian in any Codex session.\n")


def install_workbuddy():
    print("Installing to WorkBuddy (~/.workbuddy)...")
    if not SYNC_SCRIPT.exists():
        print(f"[ERR] 找不到 {SYNC_SCRIPT}")
        return 1
    rc = subprocess.call([sys.executable, str(SYNC_SCRIPT)])
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--target",
        choices=["claude", "codex", "workbuddy", "all"],
        default="claude",
        help="安装目标环境（默认 claude）",
    )
    args = ap.parse_args()

    targets = (
        ["claude", "codex", "workbuddy"] if args.target == "all" else [args.target]
    )

    rc = 0
    for t in targets:
        if t == "claude":
            install_claude()
        elif t == "codex":
            install_codex()
        elif t == "workbuddy":
            rc = install_workbuddy() or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())

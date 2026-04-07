"""
install.py — Copy obsidian skill and script to ~/.claude/

Usage:
  python install.py
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
CLAUDE_DIR = Path.home() / ".claude"
SCRIPTS_DIR = CLAUDE_DIR / "scripts"
SKILLS_DIR = CLAUDE_DIR / "skills"


def main():
    print("Installing claude-obsidian...")

    for target_dir in (SCRIPTS_DIR, SKILLS_DIR):
        target_dir.mkdir(parents=True, exist_ok=True)

    skill_target = SKILLS_DIR / "obsidian"
    if skill_target.exists():
        shutil.rmtree(skill_target)
    shutil.copytree(REPO_ROOT / "skills" / "obsidian", skill_target)

    shutil.copy(skill_target / "obsidian_writer.py", SCRIPTS_DIR / "obsidian_writer.py")
    print(f"  [OK] Script  -> {SCRIPTS_DIR / 'obsidian_writer.py'}")
    print(f"  [OK] Skill   -> {skill_target / 'SKILL.md'}")

    print()
    print("Done. Use /obsidian in any Claude Code session.")
    print("Set OBSIDIAN_VAULT_PATH env var to override the default vault path.")


if __name__ == "__main__":
    main()

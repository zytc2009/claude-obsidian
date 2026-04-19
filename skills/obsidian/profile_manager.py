"""
profile_manager.py - structured profile storage for the Obsidian vault.

Profiles live under `05-Profile/` and are updated incrementally with simple
markdown section merges. The module intentionally avoids YAML dependencies.
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import date
from pathlib import Path

PROFILE_SUBTYPES = ("personal", "projects", "tooling", "preferences")
PROFILE_TITLES = {
    "personal": "Personal",
    "projects": "Projects",
    "tooling": "Tooling",
    "preferences": "Preferences",
}
_LOG_SECTIONS = {"纠正记录", "AI 行为偏好"}
PROFILE_TEMPLATES = {
    "personal": """---
type: profile
subtype: personal
updated: {today}
version: 1
---

# Personal

## 基本信息

## 兴趣爱好

## 背景与经历
""",
    "projects": """---
type: profile
subtype: projects
updated: {today}
version: 1
---

# Projects

## 活跃项目

## 目标

## 常讨论话题
""",
    "tooling": """---
type: profile
subtype: tooling
updated: {today}
version: 1
---

# Tooling

## 编程语言

## 框架与库

## 工具链

## AI 工具
""",
    "preferences": """---
type: profile
subtype: preferences
updated: {today}
version: 1
---

# Preferences

## AI 行为偏好

## 纠正记录

## 写作风格偏好
""",
}

_PROFILE_DIR = "05-Profile"


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _profile_dir(vault: Path) -> Path:
    return vault / _PROFILE_DIR


def _normalize_subtype(subtype: str) -> str:
    value = subtype.strip().lower()
    if value not in PROFILE_TEMPLATES:
        raise ValueError(f"Unknown profile subtype: {subtype}")
    return value


def _profile_path(vault: Path, subtype: str) -> Path:
    value = _normalize_subtype(subtype)
    return _profile_dir(vault) / f"Profile - {PROFILE_TITLES[value]}.md"


def get_profile_path(vault: Path, subtype: str) -> Path:
    """Return the profile file path and ensure the parent directory exists."""
    path = _profile_path(vault, subtype)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a minimal YAML-like frontmatter block."""
    text = text or ""
    if not text.startswith("---"):
        return {}, text
    closing = text.find("---", 3)
    if closing == -1:
        return {}, text

    block = text[3:closing].strip()
    body = text[closing + 3 :]
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]

    fm: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fm[key.strip()] = value.strip()
    return fm, body


def _render_frontmatter(subtype: str, updated: str, version: int) -> str:
    return (
        "---\n"
        "type: profile\n"
        f"subtype: {subtype}\n"
        f"updated: {updated}\n"
        f"version: {version}\n"
        "---"
    )


def _section_pattern(section: str) -> re.Pattern[str]:
    escaped = re.escape(section.strip())
    return re.compile(rf"(?ms)^## {escaped}\n(.*?)(?=^## |\Z)")


def _section_key(line: str) -> str:
    link_match = re.search(r"\[\[([^\]|#]+)", line)
    if link_match:
        return link_match.group(1).strip().lower()
    return re.sub(r"\s+", " ", line).strip().lower()


def _looks_like_list(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return bool(lines) and all(line.startswith(("- ", "* ", "+ ")) for line in lines)


def _looks_like_kv(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return bool(lines) and all(":" in line and not line.startswith(("- ", "* ", "+ ")) for line in lines)


def _merge_list(existing: str, content: str) -> str:
    existing_lines = [line.rstrip() for line in existing.splitlines() if line.strip()]
    seen = {_section_key(line) for line in existing_lines}
    merged = list(existing_lines)
    for line in content.splitlines():
        cleaned = line.rstrip()
        if not cleaned.strip():
            continue
        key = _section_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return "\n".join(merged).strip()


def _merge_kv(existing: str, content: str) -> str:
    existing_lines = [line.rstrip() for line in existing.splitlines() if line.strip()]
    seen_keys = {
        line.split(":", 1)[0].strip().lower()
        for line in existing_lines
        if ":" in line
    }
    merged = list(existing_lines)
    for line in content.splitlines():
        cleaned = line.rstrip()
        if not cleaned.strip() or ":" not in cleaned:
            continue
        key = cleaned.split(":", 1)[0].strip().lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(cleaned)
    return "\n".join(merged).strip()


def _merge_log(existing: str, content: str) -> str:
    existing_lines = [line.rstrip() for line in existing.splitlines() if line.strip()]
    merged = list(existing_lines)
    today = _today_str()
    for line in content.splitlines():
        cleaned = line.rstrip()
        if not cleaned.strip():
            continue
        entry = cleaned if cleaned.startswith("[") else f"[{today}] {cleaned}"
        if entry not in merged:
            merged.append(entry)
    return "\n".join(merged).strip()


def _merge_section(section: str, existing: str, content: str) -> str:
    existing = existing.strip()
    content = content.strip()
    if not content:
        return existing
    if section.strip() in _LOG_SECTIONS:
        return _merge_log(existing, content)
    if not existing:
        return content
    if _looks_like_list(content):
        return _merge_list(existing, content)
    if _looks_like_kv(content):
        return _merge_kv(existing, content)
    if content in existing:
        return existing
    return f"{existing}\n\n{content}"


def _ensure_profile_template(vault: Path, subtype: str) -> Path:
    path = get_profile_path(vault, subtype)
    if not path.exists():
        path.write_text(
            PROFILE_TEMPLATES[_normalize_subtype(subtype)].format(today=_today_str()),
            encoding="utf-8",
        )
    return path


def upsert_profile(vault: Path, subtype: str, section: str, content: str) -> Path:
    """Merge content into a profile section and update frontmatter metadata."""
    subtype = _normalize_subtype(subtype)
    path = _ensure_profile_template(vault, subtype)
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = _strip_frontmatter(text)
    title = PROFILE_TITLES[subtype]

    heading = f"# {title}"
    if body.startswith(heading):
        body = body[len(heading) :].lstrip("\r\n")

    section_name = section.strip().removeprefix("## ").strip()
    if not section_name:
        raise ValueError("section must not be empty")

    pattern = _section_pattern(section_name)
    if pattern.search(body):

        def _replace(match: re.Match[str]) -> str:
            merged = _merge_section(section_name, match.group(1), content)
            if merged:
                return f"## {section_name}\n{merged.rstrip()}\n"
            return f"## {section_name}\n"

        body = pattern.sub(_replace, body, count=1)
    else:
        addition = content.strip()
        if body and not body.endswith("\n"):
            body += "\n"
        if body.strip():
            body = body.rstrip() + "\n\n"
        body += f"## {section_name}\n"
        if addition:
            body += f"{addition}\n"

    version = int(fm.get("version", "0") or 0) + 1
    fm_text = _render_frontmatter(subtype, _today_str(), version)
    rendered = f"{fm_text}\n\n# {title}\n\n{body.strip()}\n"
    path.write_text(rendered, encoding="utf-8")
    return path


def read_profile(vault: Path, subtype: str | None = None) -> str:
    """Read one profile subtype or concatenate all profile notes."""
    if subtype is not None:
        subtype = _normalize_subtype(subtype)
        path = _profile_path(vault, subtype)
        if not path.exists():
            return ""
        _, body = _strip_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        return body.strip()

    blocks: list[str] = []
    for item in PROFILE_SUBTYPES:
        path = _profile_path(vault, item)
        if not path.exists():
            continue
        _, body = _strip_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if body.strip():
            blocks.append(body.strip())
    return "\n\n---\n\n".join(blocks)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Profile manager for Obsidian vaults.")
    parser.add_argument(
        "--vault",
        default=os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian"),
        help="Path to the Obsidian vault",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["read", "upsert"],
        help="Operation mode",
    )
    parser.add_argument(
        "--subtype",
        default="",
        help="Profile subtype: personal, projects, tooling, preferences",
    )
    parser.add_argument(
        "--section",
        default="",
        help="Profile section title for upsert",
    )
    parser.add_argument(
        "--content",
        default="",
        help="Section content for upsert",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    vault = Path(args.vault).expanduser()

    if args.mode == "read":
        if args.subtype.strip():
            print(read_profile(vault, args.subtype.strip()))
        else:
            print(read_profile(vault))
        return

    if not args.subtype.strip():
        raise SystemExit("Error: --subtype is required for upsert")
    if not args.section.strip():
        raise SystemExit("Error: --section is required for upsert")

    path = upsert_profile(vault, args.subtype.strip(), args.section.strip(), args.content)
    print(path)


if __name__ == "__main__":
    main()

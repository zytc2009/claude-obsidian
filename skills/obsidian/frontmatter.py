"""
frontmatter.py — Markdown frontmatter & section primitives.

Pure parsing helpers, no IO. Extracted from ``obsidian_writer.py`` so
that ``workspace.py`` and higher layers can compose them without
reaching back into the legacy module.

Behavior parity: ``parse`` and ``update_field`` reproduce
``_parse_frontmatter`` and ``_set_frontmatter_field`` from
``obsidian_writer.py`` exactly so existing tests keep passing.
The new affordances are:

  - ``parse`` also returns the body
  - ``extract_wikilinks_with_alias`` exposes ``[[Note|Alias]]`` aliases
  - ``extract_aliases`` parses inline-list aliases from frontmatter
"""

from __future__ import annotations

import re
from typing import Iterable

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def parse(text: str) -> tuple[dict[str, str], str]:
    """Split ``text`` into (frontmatter dict, body).

    Mirrors the naive parser in ``obsidian_writer._parse_frontmatter``:
    each ``key: value`` line becomes a string→string entry. Multiline
    YAML values, lists, and comments are not interpreted; pass the
    raw value through :func:`extract_aliases` etc. when needed.
    """

    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()

    # Skip the trailing ``---`` and a single newline if present.
    body_start = end + 3
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return fm, text[body_start:]


def parse_dict(text: str) -> dict[str, str]:
    """Backward-compatible shim returning only the frontmatter dict."""

    fm, _ = parse(text)
    return fm


def update_field(text: str, key: str, value: str) -> str:
    """Set or insert a single-line frontmatter field.

    Behavior parity with ``obsidian_writer._set_frontmatter_field``.
    """

    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    if end == -1:
        return text

    pattern = rf"(?m)^({re.escape(key)}:\s*).*$"
    fm_block = text[:end]
    rest = text[end:]
    if re.search(pattern, fm_block):
        fm_block = re.sub(pattern, lambda m: f"{m.group(1)}{value}", fm_block)
    else:
        fm_block = fm_block.rstrip("\n") + f"\n{key}: {value}\n"
    return fm_block + rest


def read_field(text: str, key: str) -> str:
    """Return the raw value of ``key`` (or ``""`` if missing)."""

    return parse_dict(text).get(key, "")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def get_section(text: str, title: str) -> str:
    """Extract a top-level ``# Title`` section body, stripped."""

    pattern = rf"(?ms)^# {re.escape(title)}\n(.*?)(?=^# |\Z)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def replace_section(text: str, title: str, content: str) -> str:
    """Replace the body of ``# Title`` with ``content``.

    If the section does not exist, it is appended at the end with one
    blank line of separation. ``content`` is inserted verbatim
    (callers control trailing newlines).
    """

    pattern = rf"(?ms)^(# {re.escape(title)}\n)(.*?)(?=^# |\Z)"
    match = re.search(pattern, text)
    if match:
        new_body = content if content.endswith("\n") else content + "\n"
        return text[: match.start(2)] + new_body + text[match.end(2):]

    suffix = "" if text.endswith("\n") else "\n"
    body = content if content.endswith("\n") else content + "\n"
    return f"{text}{suffix}\n# {title}\n{body}"


def append_bullet_to_section(text: str, section_title: str, bullet: str) -> str:
    """Append ``- bullet`` under ``section_title``, creating it if missing.

    Behavior parity with ``obsidian_writer._append_bullet_to_section``:
    ``section_title`` is matched against the full heading line
    (e.g. ``# Sources``), not just the title text.
    """

    bullet_line = f"- {bullet}"
    if bullet_line in text:
        return text

    lines = text.splitlines(keepends=True)
    insert_at = len(lines)
    in_section = False
    for i, line in enumerate(lines):
        if line.strip() == section_title:
            in_section = True
            continue
        if in_section and line.startswith("# "):
            insert_at = i
            break

    if in_section:
        prefix = (
            ""
            if insert_at == 0
            or (insert_at > 0 and lines[insert_at - 1].endswith("\n"))
            else "\n"
        )
        lines.insert(insert_at, prefix + bullet_line + "\n")
        return "".join(lines)

    text = text.rstrip("\n")
    return f"{text}\n\n{section_title}\n{bullet_line}\n"


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------


def extract_wikilinks(text: str) -> set[str]:
    """Return wikilink targets normalized to stem only.

    Mirrors ``obsidian_writer._extract_wikilinks``. Folder prefixes are
    stripped (Obsidian resolves by stem) and aliases / heading
    fragments are dropped.
    """

    stems: set[str] = set()
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        stems.add(target.rsplit("/", 1)[-1])
    return stems


def extract_wikilinks_with_alias(text: str) -> list[tuple[str, str | None]]:
    """Return ``(stem, alias)`` for every wikilink in ``text``.

    ``alias`` is ``None`` for plain ``[[X]]`` links.
    Heading fragments (``[[X#Heading]]``) are recorded with
    ``alias=None`` (since Obsidian still resolves by stem).
    Order preserves first-occurrence order, with duplicates kept.
    """

    out: list[tuple[str, str | None]] = []
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip().rsplit("/", 1)[-1]
        alias = m.group(3)
        out.append((target, alias.strip() if alias else None))
    return out


def replace_wikilink_target(text: str, old_stem: str, new_stem: str) -> tuple[str, int]:
    """Rewrite every ``[[old_stem...]]`` occurrence to use ``new_stem``.

    Folder prefixes, heading fragments, and aliases are preserved:
      ``[[folder/Old#Section|Alias]]`` → ``[[folder/New#Section|Alias]]``

    Returns ``(new_text, count_replaced)``.
    """

    count = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal count
        full_target = m.group(1).strip()
        prefix, _, stem = full_target.rpartition("/")
        if stem != old_stem:
            return m.group(0)
        count += 1
        new_target = f"{prefix}/{new_stem}" if prefix else new_stem
        heading = m.group(2)
        alias = m.group(3)
        rebuilt = f"[[{new_target}"
        if heading is not None:
            rebuilt += f"#{heading}"
        if alias is not None:
            rebuilt += f"|{alias}"
        rebuilt += "]]"
        return rebuilt

    new_text = _WIKILINK_RE.sub(_sub, text)
    return new_text, count


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


_INLINE_LIST_RE = re.compile(r"^\[(.*)\]$")


def extract_aliases(fm: dict[str, str]) -> list[str]:
    """Parse ``aliases`` from a frontmatter dict.

    Accepts inline-list (``[A, B]``), comma-separated (``A, B``), and
    single-value forms. Block-style YAML lists (``- A`` on subsequent
    lines) are not supported because :func:`parse` collapses them.
    Empty values yield an empty list.
    """

    raw = fm.get("aliases", "").strip()
    if not raw:
        return []

    inline = _INLINE_LIST_RE.match(raw)
    if inline:
        raw = inline.group(1)

    items = [_unquote(part.strip()) for part in raw.split(",")]
    return [it for it in items if it]


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def add_alias(text: str, alias: str) -> str:
    """Append ``alias`` to the frontmatter ``aliases`` list.

    Preserves existing entries; no-op if ``alias`` is already present.
    Always emits inline-list form so :func:`extract_aliases` can read
    the result back.
    """

    fm, _ = parse(text)
    current = extract_aliases(fm)
    if alias in current:
        return text
    current.append(alias)
    quoted = ", ".join(f'"{a}"' if "," in a or ":" in a else a for a in current)
    return update_field(text, "aliases", f"[{quoted}]")


def iter_unique(items: Iterable[str]) -> list[str]:
    """Helper used by callers that want order-preserving dedup."""

    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

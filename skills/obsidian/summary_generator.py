from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


def strip_markdown(text: str) -> str:
    """Remove markdown syntax to get plain text suitable for summarization."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_\n]+)_{1,2}", r"\1", text)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _first_meaningful_paragraph(text: str, max_chars: int = 200) -> str:
    plain = strip_markdown(text)
    for para in re.split(r"\n{2,}", plain):
        para = para.strip()
        if len(para) >= 20:
            return para[:max_chars]
    return plain[:max_chars]


def _llm_summary(content: str, title: str) -> str | None:
    """Call Claude if ANTHROPIC_API_KEY is set. Returns None when unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=api_key)
    model = os.environ.get("OBSIDIAN_SUMMARY_MODEL", "claude-haiku-4-5-20251001")
    max_content = 2000
    truncated = content[:max_content] + ("..." if len(content) > max_content else "")
    prompt = (
        f"请用1-2句话概括以下文章的核心观点（不超过100字）：\n\n"
        f"标题：{title}\n\n内容：\n{truncated}"
    )
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning("LLM summary failed: %s", exc)
        return None


def generate(content: str, title: str = "", use_llm: bool = True) -> str:
    """Generate a summary with graceful LLM fallback.

    Priority: LLM (if use_llm=True and ANTHROPIC_API_KEY set) → first paragraph.
    """
    if use_llm:
        llm = _llm_summary(content, title)
        if llm:
            return llm
    return _first_meaningful_paragraph(content)

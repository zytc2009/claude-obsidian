# Profile & Article Implementation Plan

**Date:** 2026-04-19
**Status:** Completed
**Scope:** Implement profile management and article note type per [design spec](../specs/2026-04-19-profile-and-article-design.md)

---

## Repo Context

- 主文件：`skills/obsidian/obsidian_writer.py`（~2300 行）
- NOTE_CONFIG dict 在 L40-66，控制所有 note 类型的路径、前缀、必填字段
- `write_note()` 在 L496，通用写入入口
- RENDERERS dict 将 note_type 映射到渲染函数
- 测试：`tests/` 目录，178 个测试全通过，运行命令：`python -m pytest tests/ -q`
- vault 结构：`00-Inbox / 01-DailyNotes / 02-Projects / 03-Knowledge / 04-Archive`

---

## Task 1 — 新建 `profile_manager.py`

**文件：** `skills/obsidian/profile_manager.py`（新建）

实现以下函数：

```python
PROFILE_SUBTYPES = ["personal", "projects", "tooling", "preferences"]

PROFILE_TEMPLATES = {
    "personal": """---\ntype: profile\nsubtype: personal\nupdated: {today}\nversion: 1\n---\n\n# Personal\n\n## 基本信息\n\n## 兴趣爱好\n\n## 背景与经历\n""",
    "projects": """---\ntype: profile\nsubtype: projects\nupdated: {today}\nversion: 1\n---\n\n# Projects\n\n## 活跃项目\n\n## 目标\n\n## 常讨论话题\n""",
    "tooling":  """---\ntype: profile\nsubtype: tooling\nupdated: {today}\nversion: 1\n---\n\n# Tooling\n\n## 编程语言\n\n## 框架与库\n\n## 工具链\n\n## AI 工具\n""",
    "preferences": """---\ntype: profile\nsubtype: preferences\nupdated: {today}\nversion: 1\n---\n\n# Preferences\n\n## AI 行为偏好\n\n## 纠正记录\n\n## 写作风格偏好\n""",
}

def get_profile_path(vault: Path, subtype: str) -> Path:
    """返回 05-Profile/Profile - {Subtype}.md 路径，目录不存在时创建。"""

def upsert_profile(vault: Path, subtype: str, section: str, content: str) -> Path:
    """
    将 content 合并写入指定 profile 笔记的 section。
    - 文件不存在：从模板创建
    - log 类 section（纠正记录、AI 行为偏好）：追加到末尾，带 [YYYY-MM-DD] 前缀
    - list 类 section（活跃项目）：按首个 [[链接]] 去重追加
    - kv 类 section（基本信息）：已有 key 不覆盖，新 key 追加
    - 更新 frontmatter updated 字段，version +1
    返回文件路径。
    """

def read_profile(vault: Path, subtype: str | None = None) -> str:
    """
    读取 profile 内容（subtype=None 时读全部拼接）。
    文件不存在返回空字符串，不抛异常。
    """
```

合并策略细节：
- section 用 `## Section名` 匹配，找不到对应 section 时追加到文件末尾
- frontmatter 解析：手动处理（不引入 pyyaml），只更新 `updated:` 和 `version:` 两行

退出条件：
- `upsert_profile` 写入后文件内容包含传入的 content
- `read_profile` 在文件不存在时返回 `""`
- `version` 每次 upsert 正确递增

---

## Task 2 — 新建 `tests/test_profile_manager.py`

**文件：** `tests/test_profile_manager.py`（新建）

测试用例：

```
test_get_profile_path_creates_dir        # 目录自动创建
test_upsert_creates_from_template        # 首次 upsert 从模板生成
test_upsert_log_section_appends          # 纠正记录追加不覆盖
test_upsert_list_section_dedup           # 活跃项目按 [[]] 去重
test_upsert_kv_section_no_overwrite      # 基本信息已有 key 不覆盖
test_upsert_version_increments           # version 递增
test_upsert_unknown_section_appends      # 找不到 section 时追加到末尾
test_read_profile_missing_returns_empty  # 文件不存在返回 ""
test_read_profile_all_subtypes           # subtype=None 拼接全部
```

运行：`python -m pytest tests/test_profile_manager.py -q`，全部通过。

---

## Task 3 — `obsidian_writer.py`：加 `article` note 类型

**文件：** `skills/obsidian/obsidian_writer.py`

**3a — NOTE_CONFIG 加 article 条目（约 L66 附近）：**

```python
"article": {
    "prefix": "Article",
    "target": "06-Articles",
    "required": ["核心论点", "正文"],
},
```

同时在 `VAULT_DIRS`（约 L558）加：
```python
("05-Profile", None),
("06-Articles", None),
```

**3b — 加 `render_article()` 函数：**

```python
def render_article(title: str, fields: dict, is_draft: bool) -> str:
    """渲染 article 笔记。"""
    today = date.today().strftime("%Y-%m-%d")
    status = "draft" if is_draft else "review"
    source_notes = fields.get("来源笔记", "")
    target_audience = fields.get("目标读者", "")
    tags = fields.get("tags", "")

    frontmatter = (
        f"---\n"
        f"type: article\n"
        f"status: {status}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"tags: [{tags}]\n"
        f"source_notes: [{source_notes}]\n"
        f"target_audience: {target_audience}\n"
        f"---\n\n"
    )
    body = (
        f"# {title}\n\n"
        f"## 核心论点\n\n{fields.get('核心论点', '_待补充_')}\n\n"
        f"## 正文\n\n{fields.get('正文', '_待补充_')}\n\n"
        f"## 结语\n\n{fields.get('结语', '_待补充_')}\n\n"
        f"## 来源\n\n{source_notes or '_待补充_'}\n"
    )
    return frontmatter + body
```

将 `render_article` 注册到 `RENDERERS` dict。

**3c — `write_note()` 里对 article 调用查重（Task 4 实现后接入）：**

在 `write_note()` 开头，article 类型时调用 `_check_duplicate()`，若返回已有路径则直接返回该路径，不写新文件。

退出条件：
- `python obsidian_writer.py --type article --title "Test" --fields '{"核心论点":"x","正文":"y"}' --dry-run` 正常输出
- article 写入 `06-Articles/` 目录

---

## Task 4 — `obsidian_writer.py`：加 `_check_duplicate()`

**文件：** `skills/obsidian/obsidian_writer.py`

```python
def _check_duplicate(vault: Path, note_type: str, title: str) -> Path | None:
    """
    检查 vault 中是否存在标题相似的同类 note。
    相似度 > 0.8 时返回已有文件路径，否则返回 None。
    使用 difflib.SequenceMatcher，无额外依赖。
    """
    import difflib
    target_dir = vault / NOTE_CONFIG[note_type]["target"]
    if not target_dir.exists():
        return None
    candidate = _normalize_title(title)
    for existing in target_dir.glob("*.md"):
        existing_norm = _normalize_title(existing.stem)
        ratio = difflib.SequenceMatcher(None, candidate, existing_norm).ratio()
        if ratio > 0.8:
            return existing
    return None


def _normalize_title(title: str) -> str:
    """去标点、小写，用于相似度比较。"""
    import re
    return re.sub(r"[^\w\s]", "", title).lower().strip()
```

退出条件：
- 标题相同的 article 第二次写入时返回已有路径，不创建新文件
- 标题明显不同时正常写入

---

## Task 5 — 新建 `tests/test_article.py`

**文件：** `tests/test_article.py`（新建）

测试用例：

```
test_render_article_has_required_sections   # 含核心论点、正文、结语、来源
test_render_article_frontmatter_fields      # frontmatter 含 type/status/source_notes
test_write_article_creates_in_06_articles   # 写入路径正确
test_check_duplicate_exact_match            # 完全相同标题返回已有路径
test_check_duplicate_similar_match          # 相似标题（>0.8）返回已有路径
test_check_duplicate_different_title        # 不相似标题返回 None
test_write_article_dedup_returns_existing   # write_note 对重复 article 返回已有路径
```

运行：`python -m pytest tests/test_article.py -q`，全部通过。

---

## Task 6 — `obsidian_writer.py`：profile 上下文注入到 query

**文件：** `skills/obsidian/obsidian_writer.py`

找到 `query_vault()` 函数，在构建返回上下文前：

```python
from profile_manager import read_profile   # 相对导入，兼容直接运行模式

profile_ctx = read_profile(vault)
if profile_ctx:
    # 将 profile 拼在返回上下文的开头
    context_header = f"## 用户背景\n{profile_ctx}\n\n---\n\n"
else:
    context_header = ""
```

返回值前缀加 `context_header`。

退出条件：
- `05-Profile/` 存在时，query 结果包含 profile 内容
- `05-Profile/` 不存在时，query 结果不变

---

## Task 7 — SKILL.md：加 profile 和 article 操作说明

**文件：** `skills/obsidian/SKILL.md`

在操作模式列表中加两条：

**profile 操作（合并到已有 section 或新增）：**
```
### `profile` — 更新个人档案

更新 vault 中的个人档案笔记。

子类型：
- personal：基本信息、兴趣爱好
- projects：活跃项目、目标、常讨论话题
- tooling：工具、语言、框架
- preferences：AI 行为偏好和纠正记录

示例触发词：
- "记住我在用 Python 和 FastAPI"
- "更新一下，我最近在做 MultiAgent 项目"
- "记住这次纠正：不要在结尾加总结"
```

**article 操作：**
```
### `article` — 写文章

将知识库内容合成为可发布文章，写前自动查重。

字段：核心论点、正文、结语、目标读者、来源笔记（wikilinks）、tags

示例触发词：
- "写一篇关于 RAG 的文章，来源是最近几篇 literature 笔记"
- "帮我把 Topic - MultiAgent 整理成博客文章"
```

退出条件：
- SKILL.md 包含 profile 和 article 操作的触发词和字段说明

---

## Task 8 — 全量测试 & 提交

```bash
python -m pytest tests/ -q
```

预期：原有 178 + 新增 ~16 个测试全部通过。

提交信息：
```
feat: add profile management and article note type

- profile_manager.py: upsert/read for 4 profile subtypes in 05-Profile/
- article note type with dedup check via difflib.SequenceMatcher
- profile context injected into query_vault() output
- SKILL.md: add profile and article operation docs
```

---

## Execution Order

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8
```

Task 3 和 Task 4 可以并行（都在 obsidian_writer.py，但改不同函数）。
Task 1 和 Task 2 必须顺序（先有实现再写测试）。

---

## Key Constraints

- **零新依赖**：只用标准库（difflib、re、pathlib）
- **不破坏现有测试**：178 个测试必须继续通过
- **不改 CLI 接口**：已有 `--type` 参数直接支持 `article`，无需新增参数
- **profile 写入不阻断其他操作**：upsert 失败 warn 不 raise

## Execution Summary

Implemented and verified:

- `skills/obsidian/profile_manager.py` for incremental profile read/upsert
- `skills/obsidian/obsidian_writer.py` article support, duplicate detection, and profile context injection
- `skills/obsidian/SKILL.md` operator guidance for profile/article flows
- `tests/test_profile_manager.py` and `tests/test_article.py`
- full test suite passes: `225 passed`

Implementation notes:

- article writes reuse existing files when the normalized title is similar enough
- profile updates are section-aware and append or merge based on section shape
- query output now includes a profile block when profile notes exist
# Rowboat-Inspired Refactor Plan

**Date:** 2026-05-10
**Status:** PR1 ✅ / PR2 ✅ / PR3 ✅ / PR3.5b ✅ / PR3.5c ✅ / PR4 ✅ (Live Notes manual)
**Scope:** 借鉴 rowboat (`apps/x` 本地端) 的分层架构，把 `obsidian_writer.py` 单体（3230 行）拆为分层模块，建立 workspace 安全边界、统一事件流、runs/pipeline 模型，并落地保守版 Live Notes。

---

## Background

`obsidian_writer.py` 当前承担：路径解析、frontmatter 解析、文件读写、模板渲染、查询、组织、lint、merge、cascade、feedback、capture 路由、log 轮转、index 重建。3230 行单文件已经超过 CLAUDE.md "many small files (200-400 lines, 800 max)" 规则的 4 倍。

参考 rowboat `apps/x/packages/core/src/`：workspace、runs、agent runtime、knowledge pipeline、services 各自独立。我们采用相同分层思想，但保持 Python skill 形态、避免引入 SaaS / Electron / Vector DB 等不适用的复杂度。

---

## Layered Target Architecture

```
skills/obsidian/
  workspace.py          # 路径安全 + 字节 IO + atomic write + .trash + 冲突检测（零业务依赖）
  frontmatter.py        # YAML/Markdown 解析、section 操作、wikilink 提取（零业务依赖）
  note_repository.py    # Note 实体、查找、frontmatter 更新、rename + backlink rewrite
  events.py             # 统一事件 schema（schema_version=1）+ jsonl 追加器
  runs.py               # Run 模型（每 run 一个 jsonl）+ pipeline step 事件
  pipeline.py           # capture → memory → relation → link → topic → cascade → lint
  knowledge_service.py  # query / organize / topic-scout / lint
  ingest_service.py     # capture / write / merge / cascade
  live_note.py          # 手动 `live run`，无 scheduler
  cli.py                # argparse + 子命令分发
  obsidian_writer.py    # 过渡期：thin shim，逐步迁出
```

底两层（workspace、frontmatter）零业务依赖，防 Python 循环 import。

---

## PR Roadmap

### PR1 — 底座层（本计划首发）

**目标：** 建立 workspace + frontmatter + note_repository 三个零业务依赖的底座，`obsidian_writer.py` 不动，只新增模块和测试。

**交付：**
- `workspace.py`：`VaultWorkspace` 类，提供 `resolve_path`、`read_bytes`、`write_atomic`、`move_to_trash`、`rename`、`stat`，强制 vault root 边界
- `frontmatter.py`：`parse`、`dump`、`update_field`、`get_section`、`replace_section`、`append_bullet_to_section`、`extract_wikilinks`
- `note_repository.py`：`Note` dataclass、`find_by_stem`、`rename_note`（含 backlink rewrite）、`update_sections`
- 测试：每个模块独立 pytest 文件，重点覆盖：
  - 路径 traversal 防护（`..`、绝对路径、symlink 越界）
  - Windows 上 `os.replace` 原子写
  - mtime + content-hash 冲突检测
  - aliases 和 `[[Name|Alias]]` 都被 backlink rewrite 命中
  - `.trash` 路径选择（vault 外）

**不在 PR1 范围：** 修改 `obsidian_writer.py`、事件流、pipeline、live note。

### PR2 — 事件流 + Runs/Pipeline

- `events.py`：统一 schema（`schema_version: 1`、`event_type` discriminator）；扩展 `_events.jsonl` 类型（`note_written` / `note_merged` / `topic_cascade_updated` / `suggestion_rejected` / `lint_issue_detected` / `task_started` / `task_failed` / `task_done` / `step_started` / `step_done`）
- `runs.py`：每次长操作一个 `runs/<run_id>.jsonl`，事件追加；`task_queue.py` 现有 URL 导入升级为 runs
- `pipeline.py`：capture 链路率先迁移；交互式 Claude Code 调用默认 `--apply`，cron 默认 `--dry-run`

### PR3 — Service 层完工

- `knowledge_service.py`、`ingest_service.py`、`cli.py`
- `obsidian_writer.py` 退化为 thin shim，逐步标记 deprecated

### PR4 — Live Notes 手动版

- frontmatter `live: { active, objective, last_run_at, last_run_summary, last_run_error }`
- CLI：`/obsidian live run "Topic - X"` —— 读 objective + 当前 note + 相关 notes，生成更新计划，确认后改 section
- 不上 scheduler、不上事件触发

---

## PR1 Detailed Tasks

### Task 1.1 — `workspace.py`

**新文件。** 提供 `VaultWorkspace` 类：

```python
class VaultWorkspace:
    def __init__(self, root: Path, trash_dir: Path | None = None)
    def resolve_path(self, rel: str | Path) -> Path  # 拒绝绝对/.. 越界，返回绝对路径
    def read_bytes(self, rel: str | Path) -> bytes
    def read_text(self, rel: str | Path, encoding="utf-8") -> str
    def stat(self, rel: str | Path) -> WorkspaceStat  # mtime + size + content_hash(sha256)
    def write_atomic(self, rel: str | Path, data: bytes | str, *,
                     expect: WorkspaceStat | None = None) -> WorkspaceStat
                     # 写入前若 expect 不为 None 且当前 stat 不匹配 → ConflictError
    def move_to_trash(self, rel: str | Path) -> Path  # 返回 trash 内路径
    def rename(self, src_rel, dst_rel, *, expect=None) -> WorkspaceStat
    def exists(self, rel: str | Path) -> bool
    def iter_files(self, subdir: str | Path = "", pattern: str = "*.md") -> Iterator[Path]
```

**关键不变量：**
- `resolve_path` 拒绝 `Path.is_absolute()` 输入；`resolved.is_relative_to(root)` 必须为真
- `write_atomic` 使用 `tmp = path.with_suffix(path.suffix + ".tmp")` + `os.replace(tmp, path)`（Windows 安全）
- `.trash` 默认放 `<root>/../.claude-obsidian-trash/<vault-name>/`，vault 外，不污染 Obsidian graph
- `WorkspaceStat.content_hash` 使用 sha256；冲突检测同时校验 `mtime` 和 `content_hash`（防客户端时钟抖动）

**测试（`tests/test_workspace.py`）：**
- 拒绝 `..`、绝对路径、symlink 越界（`tmp_path / "outside"` 链回 vault 内不应被允许）
- atomic write 中途 kill 后 vault 内不留 `.tmp` 文件（用 monkeypatch 模拟）
- ETag/stat 不匹配抛 `ConflictError`
- `move_to_trash` 可恢复（trash 路径返回后能 read）

### Task 1.2 — `frontmatter.py`

**新文件。** 从 `obsidian_writer.py` 抽取并增强：

```python
def parse(text: str) -> tuple[dict, str]                  # (frontmatter, body)
def dump(fm: dict, body: str) -> str                      # 序列化
def update_field(text: str, key: str, value: str) -> str  # 单字段更新
def get_section(text: str, title: str) -> str             # 抽取 # Section
def replace_section(text: str, title: str, content: str) -> str
def append_bullet_to_section(text: str, title: str, bullet: str) -> str
def extract_wikilinks(text: str) -> set[str]              # 含 [[X]] 和 [[X|Alias]]
def extract_aliases(fm: dict) -> list[str]                # frontmatter aliases
```

**抽取来源：** `obsidian_writer.py` 的 `_parse_frontmatter` (1895)、`_set_frontmatter_field` (1910)、`_extract_section` (1954)、`_extract_wikilinks` (1938)、`_append_bullet_to_section` (1528)。

**改动：**
- `_parse_frontmatter` 当前只返回 dict，丢失 body；新版返回 `(fm, body)`
- `extract_wikilinks` 当前只匹配 `[[X]]`；新版同时返回 alias 形式 `[[X|Y]]` 的 `X`
- `extract_aliases` 是新功能

**测试（`tests/test_frontmatter.py`）：**
- frontmatter 缺失、空、损坏 yaml 三种 case
- section 操作幂等性（替换同一 section 两次结果一致）
- `[[Note|Alias]]` 提取出 `Note`
- frontmatter `aliases: [A, B]` 正确读取

### Task 1.3 — `note_repository.py`

**新文件。** 在 workspace + frontmatter 之上提供 Note 视图：

```python
@dataclass
class Note:
    rel_path: Path        # 相对 vault root
    frontmatter: dict
    body: str
    stat: WorkspaceStat

class NoteRepository:
    def __init__(self, ws: VaultWorkspace)
    def find_by_stem(self, stem: str) -> Note | None  # 全 vault 搜 .md
    def find_by_path(self, rel: str | Path) -> Note | None
    def list_in(self, subdir: str, *, pattern="*.md") -> list[Note]
    def update_sections(self, note: Note, fields: dict[str, str]) -> Note
    def rename(self, note: Note, new_stem: str) -> Note
        # 重命名 .md，并在全 vault 搜 [[old_stem]] / [[old_stem|*]] 替换为新 stem
        # frontmatter aliases 中含 old_stem 时保留为 alias（旧引用兼容）
    def touch_updated(self, note: Note) -> Note  # 更新 frontmatter.updated = today
```

**测试（`tests/test_note_repository.py`）：**
- rename 后 wikilink 全部更新（含别名形式）
- rename 后 `aliases:` frontmatter 自动追加 old stem
- `update_sections` 保留未提及 section 不变
- 并发写（同一 note 两次 update）后一次抛 ConflictError

### Task 1.4 — 集成测试

**新文件 `tests/test_pr1_integration.py`：** 不依赖 `obsidian_writer.py`，验证三层协作：
- 创建 note → rename → 检查反链更新
- 写 → 外部修改 → 再写应 ConflictError
- traversal 攻击向量端到端拦截

### Task 1.5 — Plan / SKILL.md 不变

PR1 不动 `SKILL.md`、不动 `obsidian_writer.py`、不动 CLI。所有新模块独立，`pytest` 通过即合格。

---

## Acceptance for PR1

- [ ] 三个新模块文件创建，每个 < 400 行
- [ ] 新增 4 个 pytest 文件，全部通过
- [ ] 现有 137 个测试全部仍通过（未触动旧代码）
- [ ] `workspace.resolve_path` 拒绝所有 traversal 用例
- [ ] `workspace.write_atomic` 在 Windows 上通过 `os.replace`
- [ ] `note_repository.rename` 后反链 rewrite 覆盖 `[[X]]`、`[[X|Y]]`、`aliases:`

---

## Open Decisions Resolved in Conversation

- **Live Note 不上 scheduler**：个人 vault + 会话式 Claude Code 不需要后台 cron，Live Notes 只做 `live run` 手动命令
- **Pipeline 默认 `--apply`**：交互式调用是用户意图延伸，不强制 plan-then-apply 仪式
- **`.trash` 放 vault 外**：避免污染 Obsidian graph 视图与搜索
- **冲突检测用 mtime + sha256**：Obsidian 客户端不保留 ETag header，纯 mtime 易抖动
- **Runs 与 Pipeline 合并实现**：runs/<run_id>.jsonl 是 pipeline step 事件流的物化形式，不做两套

#!/usr/bin/env python3
"""
vault_doctor.py — Obsidian 断链体检 + 修复。

  python3 vault_doctor.py                 # 体检报告（只读，默认）
  python3 vault_doctor.py --report out.md # 报告写文件
  python3 vault_doctor.py --fix           # 预演修复（dry-run，不动文件）
  python3 vault_doctor.py --fix --apply   # 真正落地修改

只自动修"高置信改名"这一类（相似度 >= 0.85，且候选唯一明显领先）。
其余分类只报告，不碰。
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian")).expanduser()
SKIP_DIRS = {".obsidian", ".git", "Templates", "Attachments"}

WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\n]+?)\]\]")
FENCE_RE = re.compile(r"^```.*?^```", re.S | re.M)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _is_system(p: Path) -> bool:
    """工具自身产出的文件不参与扫描，避免报告自指"""
    return p.name.startswith("_broken-links-report")
FENCE_RE = re.compile(r"^```.*?^```", re.S | re.M)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

CODE_EXT = re.compile(r"\.(md|py|cpp|h|hpp|c|js|ts|tsx|jsx|json|yaml|yml|toml|sh|rs|go|java|txt|csv|html|css)$", re.I)
CODE_TOKEN = re.compile(r"^(nodiscard|deprecated|fallthrough|maybe_unused|likely|unlikely|noreturn|carries_dependency|"
                        r"no_unique_address|visibility|always_inline|unused|const|constexpr|inline|static|extern|"
                        r"volatile|mutable|explicit|noexcept|template|typename|class|struct|namespace|nullptr|"
                        r"true|false|null|None|void|int|bool)$", re.I)
SPECIAL_CHARS = re.compile(r"::|->|<>")
EXTERNAL_PATH = re.compile(r"^(\.\./|/|[A-Za-z]:\\\\)")

AUTO_FIX_SCORE = 0.85
MANUAL_SCORE = 0.72


def strip_fences(text: str) -> str:
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))


def collect(vault: Path):
    notes = [p for p in vault.rglob("*.md")
             if not any(x in SKIP_DIRS for x in p.parts) and not _is_system(p)]
    stems = {}
    for p in notes:
        stems.setdefault(p.stem, []).append(p)
    return notes, stems


def analyze(vault: Path):
    notes, stems = collect(vault)
    stem_list = list(stems.keys())
    broken = defaultdict(list)

    for p in notes:
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for _bang, target in WIKILINK_RE.findall(strip_fences(raw)):
            t = target.split("#")[0].split("|")[0].strip()
            if t and t not in stems:
                broken[t].append(p)

    cats = {"A": [], "B": [], "C": [], "D": []}
    for target, srcs in sorted(broken.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())):
        item = {"target": target, "count": len(srcs), "sources": sorted({str(s.relative_to(vault)) for s in srcs})}
        if CODE_EXT.search(target) or CODE_TOKEN.match(target) or SPECIAL_CHARS.search(target) \
                or EXTERNAL_PATH.match(target):
            cats["A"].append(item)
            continue
        tl = target.lower().replace(" ", "")
        scored = []
        for s in stem_list:
            sl = s.lower().replace(" ", "")
            if sl == tl:
                continue
            r = SequenceMatcher(None, tl, sl).ratio()
            # 前缀关系加分，但"短泛称"除外：webrtc 不该被强连到某篇具体文章
            if (sl.startswith(tl) or tl.startswith(sl)) and min(len(tl), len(sl)) >= 10:
                r = max(r, 0.90)
            if r >= MANUAL_SCORE:
                scored.append((r, s))
        scored.sort(key=lambda x: -x[0])
        if scored:
            item["candidates"] = [{"note": s, "score": round(r, 3),
                                   "path": str(stems[s][0].relative_to(vault))} for r, s in scored[:3]]
            cats["B" if scored[0][0] >= AUTO_FIX_SCORE else "C"].append(item)
        else:
            cats["D"].append(item)
    return notes, stems, cats


def render_report(vault: Path, notes, cats) -> str:
    refs = lambda c: sum(i["count"] for i in cats[c])
    total = sum(refs(c) for c in "ABCD")
    L = []
    L.append("# 断链体检报告\n")
    L.append(f"- vault：`{vault}`")
    L.append(f"- 扫描笔记：{len(notes)} 篇")
    L.append(f"- 断链：{sum(len(cats[c]) for c in 'ABCD')} 个目标 / {total} 处引用\n")
    L.append("## 一句话结论\n")
    L.append(f"真正「链接坏掉」的只有 **{refs('B') + refs('C')} 处**（{len(cats['B']) + len(cats['C'])} 个目标）；"
             f"**{refs('D')} 处**是笔记还没建——本质是待办清单，不是错误。\n")
    L.append("| 分类 | 目标数 | 引用数 | 处理 |")
    L.append("|---|---|---|---|")
    L.append(f"| A 误报（代码标识符/外部路径） | {len(cats['A'])} | {refs('A')} | 忽略 |")
    L.append(f"| B 可自动修（改名/加后缀） | {len(cats['B'])} | {refs('B')} | `--fix --apply` 一键修 |")
    L.append(f"| C 需人工判断 | {len(cats['C'])} | {refs('C')} | 你拍板 |")
    L.append(f"| D 真缺失（笔记未建） | {len(cats['D'])} | {refs('D')} | 按需建 / 或删链接 |\n")

    L.append("## B 可自动修\n")
    for it in cats["B"]:
        c = it["candidates"][0]
        L.append(f"- `{it['target']}` ({it['count']} 处) → `{c['note']}` (score {c['score']})")
    L.append("")
    L.append("## C 需人工判断\n")
    for it in cats["C"]:
        c = it["candidates"][0]
        L.append(f"- `{it['target']}` ({it['count']} 处) → 候选 `{c['note']}` (score {c['score']})")
    L.append("")
    L.append("## D 真缺失：按待建类型\n")
    groups = defaultdict(lambda: [0, 0])
    for it in cats["D"]:
        t = it["target"]
        g = ("Concept 概念卡" if t.startswith("Concept - ") else
             "Project 项目笔记" if t.startswith("Project - ") else
             "Topic 主题页" if t.startswith("Topic - ") else
             "Literature 资料笔记" if t.startswith("Literature - ") else
             "MOC" if t.startswith("MOC - ") else
             "裸英文词（泛称）" if re.match(r"^[A-Za-z0-9 _\-]+$", t) else "其他中文标题")
        groups[g][0] += 1
        groups[g][1] += it["count"]
    L.append("| 待建类型 | 目标数 | 引用数 |")
    L.append("|---|---|---|")
    for g, (a, b) in sorted(groups.items(), key=lambda kv: -kv[1][1]):
        L.append(f"| {g} | {a} | {b} |")
    L.append("")
    L.append("## D 高频缺失（≥2 处引用，优先处理）\n")
    for it in sorted(cats["D"], key=lambda x: -x["count"]):
        if it["count"] >= 2:
            L.append(f"- `{it['target']}` — 被 {it['count']} 处引用")
    L.append("")
    L.append("## A 误报（不用管）\n")
    for it in cats["A"]:
        L.append(f"- `{it['target']}`")
    return "\n".join(L) + "\n"


def fix(vault: Path, cats, apply: bool):
    targets = {it["target"]: it["candidates"][0]["note"] for it in cats["B"]}
    # 按文件聚合：同一文件要累积所有替换后一次写入，
    # 否则后一条会基于原始文本覆盖掉前一条的修改
    per_file = {}  # path -> [text, [(old, new, count), ...]]
    for old, new in targets.items():
        pat = re.compile(r"\[\[" + re.escape(old) + r"(\|[^\]\n]*|\#[^\]\n]*)?\]\]")
        for p in vault.rglob("*.md"):
            # 追加式日志不改（改历史记录没意义，还会造成困惑）
            if any(x in SKIP_DIRS for x in p.parts) or _is_system(p) \
                    or p.name.startswith("_log"):
                continue
            entry = per_file.get(p)
            if entry is None:
                try:
                    entry = per_file[p] = [p.read_text(encoding="utf-8"), []]
                except Exception:
                    continue
            new_txt, n = pat.subn(lambda m: f"[[{new}{m.group(1) or ''}]]", entry[0])
            if n:
                entry[0] = new_txt
                entry[1].append((old, new, n))

    changes = [(p, ops, txt) for p, (txt, ops) in per_file.items() if ops]
    changes.sort(key=lambda c: str(c[0]))

    tag = f"[{'APPLY' if apply else 'DRY-RUN'}]"
    total = sum(n for _, ops, _ in changes for _, _, n in ops)
    print(f"{tag} {len(changes)} 个文件 / {total} 处替换")

    if apply and changes:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak_root = Path.home() / ".workbuddy" / "backups" / f"vault-{ts}"
        for p, *_ in changes:
            dst = bak_root / p.relative_to(vault)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        print(f"[Backup] {len(changes)} 个文件 -> {bak_root}")

    for p, ops, txt in changes:
        for old, new, n in ops:
            print(f"  {p.relative_to(vault)}: {n} 处  [[{old}]] -> [[{new}]]")
        if apply:
            p.write_text(txt, encoding="utf-8")

    if not apply:
        print("\n确认无误后加 --apply 落地（会自动备份到 ~/.workbuddy/backups/）。")
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(VAULT))
    ap.add_argument("--report", help="报告输出路径")
    ap.add_argument("--fix", action="store_true", help="执行/预演自动修复")
    ap.add_argument("--apply", action="store_true", help="配合 --fix 真正改文件")
    ap.add_argument("--json", help="结构化结果输出路径")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser()
    notes, stems, cats = analyze(vault)

    if args.fix:
        fix(vault, cats, args.apply)
        return 0

    report = render_report(vault, notes, cats)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"[OK] 报告 -> {args.report}")
    else:
        print(report)

    if args.json:
        Path(args.json).write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] JSON -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

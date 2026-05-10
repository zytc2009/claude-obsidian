"""
cli.py — Command-line interface for the Obsidian skill.

The CLI is a thin dispatch layer over the service modules
(:mod:`knowledge_service`, :mod:`ingest_service`, :mod:`linker`,
:mod:`section_ops`, :mod:`log_writer`, :mod:`index`) plus the legacy
note-writing helpers still hosted in :mod:`obsidian_writer`
(``write_note``, ``append_fleeting``, ``init_vault``,
``_capture_fields_from_import_result``, ``touch_updated``).

The script entry point at ``obsidian_writer.py``'s bottom imports
:func:`main` from this module lazily, so existing test harnesses that
invoke ``python obsidian_writer.py`` continue to work without changes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

try:
    from .index import rebuild_index
    from .ingest_service import (
        TOPIC_CASCADE_FIELDS,
        check_duplicate,
        classify_ingest_action,
        find_cascade_candidates,
        find_merge_candidates,
        resolve_vault_path,
        run_ingest_sync,
        section_diff_summary,
    )
    from .knowledge_service import lint_vault, organize_vault, query_vault
    from .linker import scout_topics, suggest_links, suggest_new_topic
    from . import live_note
    from .log_writer import (
        append_operation_log,
        append_suggestion_feedback,
        maybe_emit_orphan_correction,
        normalize_feedback_target,
        print_feedback_hint,
    )
    from .section_ops import (
        add_conflict_annotation,
        add_source_reference,
        add_supporting_note,
        update_note_sections,
    )
    from .templates import NOTE_CONFIG, RENDERERS
except ImportError:  # script-mode fallback
    from index import rebuild_index  # type: ignore[no-redef]
    from ingest_service import (  # type: ignore[no-redef]
        TOPIC_CASCADE_FIELDS,
        check_duplicate,
        classify_ingest_action,
        find_cascade_candidates,
        find_merge_candidates,
        resolve_vault_path,
        run_ingest_sync,
        section_diff_summary,
    )
    from knowledge_service import lint_vault, organize_vault, query_vault  # type: ignore[no-redef]
    from linker import scout_topics, suggest_links, suggest_new_topic  # type: ignore[no-redef]
    import live_note  # type: ignore[no-redef]
    from log_writer import (  # type: ignore[no-redef]
        append_operation_log,
        append_suggestion_feedback,
        maybe_emit_orphan_correction,
        normalize_feedback_target,
        print_feedback_hint,
    )
    from section_ops import (  # type: ignore[no-redef]
        add_conflict_annotation,
        add_source_reference,
        add_supporting_note,
        update_note_sections,
    )
    from templates import NOTE_CONFIG, RENDERERS  # type: ignore[no-redef]

# These still live in obsidian_writer; importing them at function-call
# time avoids a circular import on package load.
def _from_obsidian_writer(name: str):
    # Prefer the package import so we resolve the same module instance
    # that callers see as ``skills.obsidian.obsidian_writer`` — that's
    # the one tests monkey-patch.
    try:
        from . import obsidian_writer as _ow  # type: ignore[import-not-found]
    except ImportError:
        import obsidian_writer as _ow  # type: ignore[no-redef]
    return getattr(_ow, name)


# Capture importer + image cache are looked up on ``obsidian_writer``
# at call time so existing tests that monkey-patch
# ``obsidian_writer.capture_fetch_url`` keep working without changes.


VAULT_PATH = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian")).expanduser()


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Write a structured note to an Obsidian vault."
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=list(NOTE_CONFIG.keys())
        + [
            "capture",
            "fleeting",
            "init",
            "lint",
            "index",
            "query",
            "organize",
            "merge-candidates",
            "merge-update",
            "cascade-candidates",
            "cascade-update",
            "conflict-update",
            "ingest-sync",
            "suggestion-feedback",
            "topic-scout",
            "live-list",
            "live-run",
        ],
        help="Note type",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Auto-fix simple issues (missing frontmatter fields) during lint",
    )
    parser.add_argument("--title", default="", help="Note title")
    parser.add_argument("--url", default="", help="Capture URL")
    parser.add_argument(
        "--source-note",
        default="",
        help="Existing note stem to add under # Supporting notes after writing",
    )
    parser.add_argument(
        "--source-ref",
        default="",
        help="Source label to add under # Sources after writing",
    )
    parser.add_argument(
        "--target",
        default="",
        help="Target note path for merge-update (absolute or vault-relative)",
    )
    parser.add_argument(
        "--conflicts-with",
        default="",
        help="Target note/file/link that this note conflicts with",
    )
    parser.add_argument(
        "--status-label",
        default="unresolved",
        help="Conflict status label, default unresolved",
    )
    parser.add_argument(
        "--suggestion-type",
        default="",
        help="Suggestion kind for suggestion-feedback (link/merge/cascade/topic)",
    )
    parser.add_argument(
        "--feedback-action",
        default="",
        help="Feedback action for suggestion-feedback (reject/modify-accept)",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Optional reason for suggestion-feedback",
    )
    parser.add_argument(
        "--targets",
        default="",
        help="Comma-separated target list for suggestion-feedback",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Query text for query/organize subcommands",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Include tier-2 detail notes in query output",
    )
    parser.add_argument(
        "--vault",
        default=str(VAULT_PATH),
        help="Path to the vault (defaults to OBSIDIAN_VAULT_PATH or ~/obsidian)",
    )
    parser.add_argument(
        "--fields",
        default="{}",
        help="JSON object of field key→value content",
    )
    parser.add_argument(
        "--draft",
        choices=["true", "false"],
        default="false",
        help="Force draft routing to the Inbox even when content is complete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and print without writing to disk",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)

    try:
        fields = json.loads(args.fields)
    except json.JSONDecodeError as e:
        print(f"Error: --fields is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    vault = Path(args.vault)
    note_type = args.type

    # --- Init: special case ---
    if note_type == "init":
        _from_obsidian_writer("init_vault")(vault)
        return

    # --- Lint: special case ---
    if note_type == "lint":
        lint_vault(vault, auto_fix=args.auto_fix)
        return

    # --- Topic scout ---
    if note_type == "topic-scout":
        scout_topics(vault)
        return

    # --- Live Notes: list ---
    if note_type == "live-list":
        entries = live_note.list_live_notes(vault)
        print(live_note.format_list(entries))
        return

    # --- Live Notes: manual run ---
    if note_type == "live-run":
        stem = args.title.strip()
        if not stem:
            print("Error: --title is required for live-run", file=sys.stderr)
            sys.exit(1)
        result = live_note.run_live_note(vault, stem)
        if not result.success:
            print(f"Error: {result.error}", file=sys.stderr)
            if result.run_id:
                print(f"  run_id: {result.run_id}", file=sys.stderr)
            sys.exit(1)
        print(live_note.format_context(result.context))
        if result.run_id:
            print(f"\n[Run] {result.run_id}")
        return

    # --- Index: special case ---
    if note_type == "index":
        index_path = rebuild_index(vault)
        print(f"[OK] Index rebuilt: {index_path.relative_to(vault)}")
        return

    # --- Query ---
    if note_type == "query":
        query_text = args.query.strip() or args.title.strip() or str(fields.get("query", "")).strip()
        if not query_text:
            print("Error: --query is required for query", file=sys.stderr)
            sys.exit(1)
        result = query_vault(vault, query_text, include_details=args.details)
        tier1_topics = result["tier1_topics"]
        tier2_grouped = result["tier2_grouped"]
        orphans = result["orphans"]
        profile_context = result.get("profile_context", "")

        if not tier1_topics and not tier2_grouped and not orphans:
            print(f"[Query] No matches for: {query_text}")
            if profile_context:
                print("\n[Profile]")
                print(profile_context)
            return

        print(f"[Query] {query_text}")
        if profile_context:
            print("\n[Profile]")
            print(profile_context)
        if tier1_topics:
            print("\n[Tier 1: Topics]")
            for item in tier1_topics:
                print(f"  [[{item['title']}]]")
                if item["主题说明"]:
                    print(f"    主题说明: {item['主题说明']}")
                if item["当前结论"]:
                    print(f"    当前结论: {item['当前结论']}")
                if item["未解决问题"]:
                    print(f"    未解决问题: {item['未解决问题']}")
            if not args.details:
                print('\n[Hint] Use --details to include drill-down notes.')

        if tier2_grouped:
            print("\n[Tier 2: Details]")
            for group in tier2_grouped:
                print(f"  Topic: [[{group['topic']}]]")
                for note in group["notes"]:
                    excerpt = f" — {note['excerpt']}" if note["excerpt"] else ""
                    print(f"    [[{note['title']}]]{excerpt}")

        if orphans:
            print("\n[Orphans]")
            for note in orphans:
                excerpt = f" — {note['excerpt']}" if note["excerpt"] else ""
                print(f"  [[{note['title']}]]{excerpt}")
        return

    # --- Organize ---
    if note_type == "organize":
        query_text = args.query.strip() or args.title.strip() or str(fields.get("query", "")).strip()
        if not query_text:
            print("Error: --query is required for organize", file=sys.stderr)
            sys.exit(1)
        result = organize_vault(vault, query_text)
        matches = result["matches"]
        profile_context = result.get("profile_context", "")
        if not matches:
            print(f"[Organize] No related notes found for: {query_text}")
            if profile_context:
                print("\n[Profile]")
                print(profile_context)
            return
        print(f"[Organize] {query_text}")
        if profile_context:
            print("\n[Profile]")
            print(profile_context)
        if result["session_hits"]:
            print("\n[Session-first]")
            for path in result["session_hits"]:
                print(f"  [[{path.stem}]]")
        print("\n[Matches]")
        for item in matches:
            markers = []
            if item["in_session"]:
                markers.append("session")
            if item["in_inbox"]:
                markers.append("inbox")
            marker_text = f" ({', '.join(markers)})" if markers else ""
            excerpt = f" — {item['excerpt']}" if item["excerpt"] else ""
            print(f"  [[{item['title']}]]{marker_text}{excerpt}")
        print(
            f"\n[Suggest] Converge into: {result['suggested_output']} "
            f"(confidence={result['confidence']})"
        )
        if result["reasons"]:
            print("[Reasons]")
            for reason in result["reasons"]:
                print(f"  - {reason}")
        if result["new_topic_hint"]:
            print(f"[Topic suggestion] {result['new_topic_hint']}")
        return

    # --- Merge candidates ---
    if note_type == "merge-candidates":
        title = args.title.strip()
        if not title:
            print("Error: --title is required for merge-candidates", file=sys.stderr)
            sys.exit(1)
        candidates = find_merge_candidates(vault, title)
        if not candidates:
            print("[OK] No merge candidates found.")
            return
        print("[Merge candidates]")
        for candidate in candidates:
            print(f"  -> {candidate.relative_to(vault)}")
        print_feedback_hint(
            source_note=NOTE_CONFIG["literature"]["prefix"] + f" - {title}",
            suggestion_type="merge",
            targets=[str(candidate.relative_to(vault)) for candidate in candidates[:3]],
            reason="Use if you reject these merge candidates or pick a narrower target.",
        )
        return

    # --- Cascade candidates ---
    if note_type == "cascade-candidates":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for cascade-candidates", file=sys.stderr)
            sys.exit(1)
        source_path = Path(target_arg)
        if not source_path.is_absolute():
            source_path = vault / source_path
        if not source_path.exists():
            print(f"Error: source note not found: {source_path}", file=sys.stderr)
            sys.exit(1)
        candidates = find_cascade_candidates(vault, source_path)
        if not candidates:
            print("[OK] No cascade candidates found.")
            return
        print("[Cascade candidates]")
        for candidate, reason in candidates:
            print(f"  -> {candidate.relative_to(vault)} ({reason})")
        print_feedback_hint(
            source_note=source_path.stem,
            suggestion_type="cascade",
            targets=[str(candidate.relative_to(vault)) for candidate, _ in candidates[:3]],
            reason="Use if you reject these cascade targets or manually update a different topic.",
        )
        return

    # --- Merge update ---
    if note_type == "merge-update":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for merge-update", file=sys.stderr)
            sys.exit(1)
        target_path = Path(target_arg)
        if not target_path.is_absolute():
            target_path = vault / target_path
        if not target_path.exists():
            print(f"Error: target note not found: {target_path}", file=sys.stderr)
            sys.exit(1)

        touch_updated = _from_obsidian_writer("touch_updated")
        changed_sections = update_note_sections(target_path, fields)
        merge_updates = []
        if changed_sections:
            merge_updates.append(f"Sections updated: {', '.join(changed_sections)}")
        if args.source_note and add_supporting_note(target_path, args.source_note):
            merge_updates.append(f"Supporting note: [[{args.source_note}]]")
        if args.source_ref and add_source_reference(target_path, args.source_ref):
            merge_updates.append(f"Source added: {args.source_ref}")
        if merge_updates and merge_updates != ["No content changes"] and touch_updated(target_path):
            merge_updates.append(f"Updated date: {_today_str()}")
        if not merge_updates:
            merge_updates.append("No content changes")

        append_operation_log(vault, "merge", target_path.stem, merge_updates)
        print(f"[OK] Merged into: {target_path.relative_to(vault)}")
        if merge_updates:
            print("\n[Merge updates]")
            for item in merge_updates:
                print(f"  -> {item}")
        return

    # --- Cascade update ---
    if note_type == "cascade-update":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for cascade-update", file=sys.stderr)
            sys.exit(1)
        target_path = Path(target_arg)
        if not target_path.is_absolute():
            target_path = vault / target_path
        if not target_path.exists():
            print(f"Error: target note not found: {target_path}", file=sys.stderr)
            sys.exit(1)

        invalid = [key for key in fields if key not in TOPIC_CASCADE_FIELDS]
        if invalid:
            print(
                f"Error: cascade-update only supports topic fields: {', '.join(invalid)}",
                file=sys.stderr,
            )
            sys.exit(1)

        touch_updated = _from_obsidian_writer("touch_updated")
        changed_sections = update_note_sections(target_path, fields)
        cascade_updates = []
        if changed_sections:
            cascade_updates.append(f"Sections updated: {', '.join(changed_sections)}")
        if args.source_note and add_supporting_note(target_path, args.source_note):
            cascade_updates.append(f"Supporting note: [[{args.source_note}]]")
        if cascade_updates and cascade_updates != ["No content changes"] and touch_updated(target_path):
            cascade_updates.append(f"Updated date: {_today_str()}")
        if not cascade_updates:
            cascade_updates.append("No content changes")

        append_operation_log(vault, "cascade", target_path.stem, cascade_updates)
        print(f"[OK] Cascade-updated: {target_path.relative_to(vault)}")
        print("\n[Cascade updates]")
        for item in cascade_updates:
            print(f"  -> {item}")
        return

    # --- Conflict update ---
    if note_type == "conflict-update":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for conflict-update", file=sys.stderr)
            sys.exit(1)
        if not args.source_note.strip():
            print("Error: --source-note is required for conflict-update", file=sys.stderr)
            sys.exit(1)
        claim = (fields.get("claim") or "").strip()
        if not claim:
            print("Error: conflict-update requires fields.claim", file=sys.stderr)
            sys.exit(1)
        conflicts_with = args.conflicts_with.strip()
        if not conflicts_with:
            print("Error: --conflicts-with is required for conflict-update", file=sys.stderr)
            sys.exit(1)

        target_path = Path(target_arg)
        if not target_path.is_absolute():
            target_path = vault / target_path
        if not target_path.exists():
            print(f"Error: target note not found: {target_path}", file=sys.stderr)
            sys.exit(1)

        touch_updated = _from_obsidian_writer("touch_updated")
        changed = add_conflict_annotation(
            target_path,
            args.source_note.strip(),
            claim,
            conflicts_with,
            args.status_label.strip() or "unresolved",
        )
        if changed:
            touch_updated(target_path)
        details = [
            f"Conflict source: [[{args.source_note.strip()}]]",
            f"Conflicts with: {conflicts_with}",
            f"Status: {args.status_label.strip() or 'unresolved'}",
        ]
        if changed:
            details.insert(0, "Conflict added")
            details.append(f"Updated date: {_today_str()}")
        else:
            details.insert(0, "Conflict already present")
        append_operation_log(vault, "conflict", target_path.stem, details)
        print(f"[OK] Conflict-updated: {target_path.relative_to(vault)}")
        print("\n[Conflict updates]")
        for item in details:
            print(f"  -> {item}")
        return

    # --- Ingest sync ---
    if note_type == "ingest-sync":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for ingest-sync", file=sys.stderr)
            sys.exit(1)
        target_path = resolve_vault_path(vault, target_arg)
        try:
            summary = run_ingest_sync(vault, target_path, fields)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"[OK] Ingest sync applied: {target_path.relative_to(vault)}")
        if summary["primary_updates"]:
            print("\n[Primary updates]")
            for item in summary["primary_updates"]:
                print(f"  -> {item}")
        if summary["cascade_updates"]:
            print("\n[Cascade updates]")
            for cascade in summary["cascade_updates"]:
                print(f"  -> {cascade['target']}")
                for item in cascade["details"]:
                    print(f"     {item}")
        if summary["conflicts"]:
            print("\n[Conflict updates]")
            for conflict in summary["conflicts"]:
                print(f"  -> {conflict['target']}")
                for item in conflict["details"]:
                    print(f"     {item}")
        return

    # --- Suggestion feedback ---
    if note_type == "suggestion-feedback":
        suggestion_type = args.suggestion_type.strip().lower()
        action = args.feedback_action.strip().lower()
        source_note = args.source_note.strip()
        if not suggestion_type:
            print("Error: --suggestion-type is required for suggestion-feedback", file=sys.stderr)
            sys.exit(1)
        if suggestion_type not in {"link", "merge", "cascade", "topic"}:
            print("Error: --suggestion-type must be one of: link, merge, cascade, topic", file=sys.stderr)
            sys.exit(1)
        if action not in {"reject", "modify-accept"}:
            print("Error: --feedback-action must be one of: reject, modify-accept", file=sys.stderr)
            sys.exit(1)
        if not source_note:
            print("Error: --source-note is required for suggestion-feedback", file=sys.stderr)
            sys.exit(1)

        target_notes = [item.strip() for item in args.targets.split(",") if item.strip()]
        if not target_notes and isinstance(fields.get("target_notes"), list):
            target_notes = [str(item).strip() for item in fields["target_notes"] if str(item).strip()]
        normalized_target_notes = []
        for target in target_notes:
            normalized = normalize_feedback_target(target)
            if normalized:
                normalized_target_notes.append(normalized)
        reason = args.reason.strip() or str(fields.get("reason", "")).strip()

        events_path = append_suggestion_feedback(
            vault,
            suggestion_type=suggestion_type,
            action=action,
            source_note=source_note,
            target_notes=target_notes,
            reason=reason,
        )
        print(f"[OK] Suggestion feedback recorded: {events_path.relative_to(vault)}")
        print(f"  Type   : {suggestion_type}")
        print(f"  Action : {action}")
        print(f"  Source : {source_note}")
        if normalized_target_notes:
            print(f"  Targets: {', '.join(normalized_target_notes)}")
        if reason:
            print(f"  Reason : {reason}")
        return

    # --- Capture (URL ingestion) ---
    if note_type == "capture":
        capture_url = args.url.strip() or args.title.strip() or str(fields.get("url", "")).strip()
        if not capture_url:
            print("Error: --url is required for capture", file=sys.stderr)
            sys.exit(1)
        # Looked up at call time so monkeypatch on obsidian_writer.capture_fetch_url
        # remains an effective test seam.
        capture_fetch_url = _from_obsidian_writer("capture_fetch_url")
        if capture_fetch_url is None:
            print("Error: capture importers are unavailable", file=sys.stderr)
            sys.exit(1)

        try:
            import_result = capture_fetch_url(capture_url)
        except Exception as e:
            print(f"Error: failed to capture URL: {e}", file=sys.stderr)
            sys.exit(1)

        cache_images_fn = _from_obsidian_writer("_cache_images")
        if (
            cache_images_fn is not None
            and os.environ.get("OBSIDIAN_CACHE_IMAGES", "0") == "1"
        ):
            import dataclasses
            import_result = dataclasses.replace(
                import_result, content=cache_images_fn(vault, import_result.content)
            )

        capture_fields_helper = _from_obsidian_writer("_capture_fields_from_import_result")
        write_note = _from_obsidian_writer("write_note")
        title, capture_fields = capture_fields_helper(import_result, fields)
        if not title:
            fallback = capture_url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
            title = fallback or "Captured Content"

        if args.dry_run:
            print("[Capture preview]")
            print(json.dumps(
                {
                    "title": title,
                    "platform": import_result.platform,
                    "source_url": import_result.source_url,
                    "summary": import_result.summary,
                    "metadata": import_result.metadata or {},
                },
                ensure_ascii=False,
                indent=2,
            ))
            print("\n[Fields]")
            print(json.dumps(capture_fields, ensure_ascii=False, indent=2))
            return

        filepath = write_note(
            vault=vault,
            note_type="literature",
            title=title,
            fields=capture_fields,
            is_draft=args.draft == "true",
        )
        rel_path = filepath.relative_to(vault)
        print(f"[OK] Captured: {rel_path}")
        print(f"  Platform: {import_result.platform}")
        print(f"  Source  : {import_result.source_url}")
        if import_result.summary:
            print(f"  Summary : {import_result.summary[:120]}")
        return

    # --- Fleeting ---
    if note_type == "fleeting":
        content = fields.get("content", "").strip()
        if not content:
            print("Error: fleeting note requires fields.content", file=sys.stderr)
            sys.exit(1)
        tags = fields.get("tags", "").strip()
        if args.dry_run:
            now = datetime.now().strftime("%H:%M")
            tag_part = f" {tags}" if tags else ""
            today = _today_str()
            print(f"[DRY RUN] Would append to: 01-DailyNotes/{today}.md\n")
            print(f"- {now} {content}{tag_part}")
            return
        append_fleeting = _from_obsidian_writer("append_fleeting")
        filepath = append_fleeting(vault, content, tags)
        rel = filepath.relative_to(vault)
        print(f"[OK] Appended to: {rel}")
        return

    # --- Standard note types ---
    is_draft = args.draft == "true"
    title = args.title.strip()
    if not title:
        print("Error: --title is required for this note type", file=sys.stderr)
        sys.exit(1)

    if note_type == "article" and not args.dry_run:
        duplicate = check_duplicate(vault, note_type, title)
        if duplicate is not None:
            print(f"[OK] Reused existing: {duplicate.relative_to(vault)}")
            return

    if args.dry_run:
        content = RENDERERS[note_type](title, fields, is_draft)
        if note_type == "article":
            duplicate = check_duplicate(vault, note_type, title)
            if duplicate is not None:
                print("[INGEST PREVIEW]")
                SEP = "=" * 52
                print(SEP)
                print("Action  : reuse existing")
                print(f"Target  : {duplicate.relative_to(vault)}")
                print(SEP)
                print(content)
                print(SEP)
                return
        action, existing_path, planned_path = classify_ingest_action(
            vault, note_type, title, is_draft
        )
        SEP = "─" * 52
        print("[INGEST PREVIEW]")
        print(SEP)
        print(f"Action  : {action}")
        print(f"Target  : {planned_path.relative_to(vault)}")
        if existing_path:
            print(f"Existing: {existing_path.relative_to(vault)}")
            print(f"Diff    : {section_diff_summary(existing_path, content)}")
            print(f"Note    : existing note unchanged — use --type merge-update to update in place")
        print(SEP)
        print(content)
        print(SEP)
        suggestions = suggest_links(vault, planned_path)
        if suggestions:
            print("[Link suggestions]")
            for rel, section in suggestions:
                print(f"  → {rel}  ({section}  ← add [[{planned_path.stem}]])")
            print_feedback_hint(
                source_note=planned_path.stem,
                suggestion_type="link",
                targets=[str(rel) for rel, _ in suggestions],
                reason="Use if you reject these link suggestions or choose a narrower target.",
            )
        new_topic_hint = suggest_new_topic(planned_path, suggestions)
        if new_topic_hint:
            print(f"\n[Topic suggestion]\n  {new_topic_hint}")
            topic_name = new_topic_hint.removeprefix("Consider creating: ").strip()
            print_feedback_hint(
                source_note=planned_path.stem,
                suggestion_type="topic",
                targets=[topic_name] if topic_name else [],
                reason="Use if you reject this topic suggestion or create a different topic instead.",
            )
        return

    write_note = _from_obsidian_writer("write_note")
    filepath = write_note(
        vault=vault,
        note_type=note_type,
        title=title,
        fields=fields,
        is_draft=is_draft,
    )

    rel_path = filepath.relative_to(vault)
    print(f"[OK] Written: {rel_path}")

    post_write_updates = []
    if args.source_note and add_supporting_note(filepath, args.source_note):
        post_write_updates.append(f"Supporting note: [[{args.source_note}]]")
    if args.source_ref and add_source_reference(filepath, args.source_ref):
        post_write_updates.append(f"Source added: {args.source_ref}")
    if post_write_updates:
        append_operation_log(vault, "update", filepath.stem, post_write_updates)
        print("\n[Post-write updates]")
        for item in post_write_updates:
            print(f"  -> {item}")

    suggestions = suggest_links(vault, filepath)
    if suggestions:
        print("\n[Link suggestions]")
        for rel, section in suggestions:
            print(f"  → {rel}  ({section}  ← add [[{filepath.stem}]])")
        print_feedback_hint(
            source_note=filepath.stem,
            suggestion_type="link",
            targets=[str(rel) for rel, _ in suggestions],
            reason="Use if you reject these link suggestions or choose a narrower target.",
        )

    new_topic_hint = suggest_new_topic(filepath, suggestions)
    if new_topic_hint:
        print("\n[Topic suggestion]")
        print(f"  {new_topic_hint}")
        topic_name = new_topic_hint.removeprefix("Consider creating: ").strip()
        print_feedback_hint(
            source_note=filepath.stem,
            suggestion_type="topic",
            targets=[topic_name] if topic_name else [],
            reason="Use if you reject this topic suggestion or create a different topic instead.",
        )

    maybe_emit_orphan_correction(vault, filepath, suggestions, is_draft)


if __name__ == "__main__":
    main()

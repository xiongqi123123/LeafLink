"""Command-line interface for leaflink."""

from __future__ import annotations

import argparse
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Callable, Sequence

from leaflink.auth.manager import AuthManager
from leaflink.client.overleaf_client import OverleafClient, OverleafClientProtocol
from leaflink.config import ConfigStore, SUPPORTED_BASE_URLS
from leaflink.exceptions import ClientError, LeafsyncError, ProjectError, SyncConflictError
from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.conflict import ConflictStrategy, MergeAnalysis
from leaflink.sync.engine import ChangeDetails, LocalChangeEvent, SyncEngine, SyncLifecycleEvent, SyncReport
from leaflink.sync.state import StateStore
from leaflink.utils.console import format_label, print_console, style_text, use_color
from leaflink.utils.logging import configure_logging
from leaflink.utils.time import format_display_time, utc_now_iso

ClientFactory = Callable[[str], OverleafClientProtocol]


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leaflink", description="Sync local folders with Overleaf projects.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Login via browser or imported cookies.")
    login_parser.add_argument("--base-url", default=None, help="Overleaf base URL.")
    login_parser.add_argument("--cookie-file", type=Path, default=None, help="Import cookies from JSON.")

    logout_parser = subparsers.add_parser("logout", help="Clear saved authentication state.")
    logout_parser.add_argument("--base-url", default=None, help="Only remove credentials for one base URL.")

    auth_parser = subparsers.add_parser("auth", help="Authentication helpers.")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_import_parser = auth_subparsers.add_parser("import", help="Import cookies from JSON.")
    auth_import_parser.add_argument("--base-url", default=None, help="Overleaf base URL.")
    auth_import_parser.add_argument("--cookie-file", type=Path, required=True, help="JSON cookie file.")

    list_parser = subparsers.add_parser("list", help="List accessible projects.")
    list_parser.add_argument("--base-url", default=None, help="Overleaf base URL.")

    clone_parser = subparsers.add_parser("clone", help="Clone a remote project to a local directory.")
    clone_parser.add_argument("project_parts", nargs="+", help="Project URL, project id, or exact project name.")
    clone_parser.add_argument("--target-dir", type=Path, default=None, help="Target directory.")
    clone_parser.add_argument("--base-url", default=None, help="Overleaf base URL.")

    pull_parser = subparsers.add_parser("pull", help="Pull remote changes into the current project.")
    _add_project_command_options(pull_parser)

    push_parser = subparsers.add_parser("push", help="Push local changes to the remote project.")
    _add_project_command_options(push_parser)

    status_parser = subparsers.add_parser("status", help="Show local and remote changes without syncing.")
    status_parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory.")
    status_parser.add_argument("--ignore-file", default=".leafignore", help="Ignore file name.")

    download_parser = subparsers.add_parser("download", help="Download the compiled PDF.")
    download_parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory.")
    download_parser.add_argument("--output", type=Path, default=None, help="Output PDF path.")

    sync_parser = subparsers.add_parser("sync", help="Pseudo real-time local/remote synchronization.")
    sync_parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory.")
    sync_parser.add_argument("--interval", type=float, default=10.0, help="Remote polling interval in seconds.")
    sync_parser.add_argument("--debounce", type=float, default=1.5, help="Local change debounce in seconds.")
    sync_parser.add_argument("--ignore-file", default=".leafignore", help="Ignore file name.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Print actions without applying them.")
    sync_parser.add_argument("--once", action="store_true", help="Run one pull+push cycle and exit.")
    sync_parser.add_argument(
        "--conflict-strategy",
        choices=["keep-local", "keep-remote", "duplicate-both"],
        default=None,
        help="Apply a conflict strategy instead of aborting.",
    )
    return parser


def _add_project_command_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory.")
    parser.add_argument("--ignore-file", default=".leafignore", help="Ignore file name.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without applying them.")
    parser.add_argument(
        "--conflict-strategy",
        choices=["keep-local", "keep-remote", "duplicate-both"],
        default=None,
        help="Apply a conflict strategy instead of aborting.",
    )


def main(argv: Sequence[str] | None = None, client_factory: ClientFactory | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    config_store = ConfigStore()
    config = config_store.load()
    auth_manager = AuthManager()

    try:
        match args.command:
            case "login":
                base_url = _pick_base_url(args.base_url, config.default_base_url)
                session = auth_manager.login(base_url, cookie_file=args.cookie_file)
                config.default_base_url = session.base_url
                config_store.save(config)
                print_console("ok", f"Saved session for {session.base_url}")
            case "logout":
                removed = auth_manager.logout(args.base_url)
                if removed:
                    print_console("ok", "Removed saved auth session.")
                else:
                    print_console("warn", "No saved auth session found.")
            case "auth":
                if args.auth_command == "import":
                    base_url = _pick_base_url(args.base_url, config.default_base_url)
                    session = auth_manager.login(base_url, cookie_file=args.cookie_file)
                    config.default_base_url = session.base_url
                    config_store.save(config)
                    print_console("ok", f"Imported cookies for {session.base_url}")
            case "list":
                client = _make_client(_pick_base_url(args.base_url, config.default_base_url), auth_manager, client_factory)
                projects = client.list_projects()
                if not projects:
                    print_console("warn", "No projects found.")
                else:
                    _print_project_list(projects)
            case "clone":
                project_ref, target_dir = _resolve_clone_inputs(args.project_parts, args.target_dir)
                base_url = _pick_base_url(args.base_url, config.default_base_url, project_ref)
                client = _make_client(base_url, auth_manager, client_factory)
                info = client.resolve_project(project_ref)
                target_dir = target_dir or Path(_slugify(info.name))
                target_dir.mkdir(parents=True, exist_ok=True)
                metadata = ProjectMetadataStore(target_dir)
                metadata.init(
                    ProjectConfig(
                        project_id=info.project_id,
                        base_url=base_url,
                        project_name=info.name,
                        last_known_remote_revision=info.revision,
                    )
                )
                engine = SyncEngine(target_dir, client)
                archive = client.download_project_archive(info.project_id)
                engine.clone_into(archive, revision=info.revision)
                print_console("ok", f"Cloned {info.name} into {target_dir}")
            case "pull":
                engine = _load_engine(args.project_dir, args.ignore_file, auth_manager, client_factory)
                report = engine.pull(
                    strategy=args.conflict_strategy,
                    dry_run=args.dry_run,
                    conflict_resolver=None if args.conflict_strategy else _interactive_conflict_resolver,
                )
                _print_sync_report(report, prefix="pull")
            case "push":
                engine = _load_engine(args.project_dir, args.ignore_file, auth_manager, client_factory)
                report = engine.push(
                    strategy=args.conflict_strategy,
                    dry_run=args.dry_run,
                    conflict_resolver=None if args.conflict_strategy else _interactive_conflict_resolver,
                )
                _print_sync_report(report, prefix="push")
            case "status":
                engine = _load_engine(args.project_dir, args.ignore_file, auth_manager, client_factory)
                report = engine.status()
                _print_status(report)
            case "download":
                engine = _load_engine(args.project_dir, ".leafignore", auth_manager, client_factory)
                destination = engine.download_pdf(args.output)
                print_console("ok", f"Downloaded PDF to {destination}")
            case "sync":
                engine = _load_engine(args.project_dir, args.ignore_file, auth_manager, client_factory)
                _print_sync_event(
                    SyncLifecycleEvent(
                        stage="startup",
                        message=f"Preparing sync service for {engine.project.project_name}.",
                    )
                )
                if args.dry_run:
                    _print_sync_event(
                        SyncLifecycleEvent(
                            stage="startup",
                            message="Dry-run mode is enabled. Changes will only be reported.",
                        )
                    )
                if args.once:
                    _print_sync_event(
                        SyncLifecycleEvent(
                            stage="startup",
                            message="One-shot mode enabled. leaflink will check once and exit.",
                        )
                    )
                engine.run_sync_loop(
                    interval=args.interval,
                    debounce=args.debounce,
                    strategy=args.conflict_strategy,
                    dry_run=args.dry_run,
                    once=args.once,
                    on_event=_print_sync_event,
                    conflict_resolver=None if args.conflict_strategy else _interactive_conflict_resolver,
                )
            case _:
                parser.error("Unknown command")
    except KeyboardInterrupt:
        print_console("warn", "Stopped.", stream=sys.stderr)
        return 130
    except SyncConflictError as exc:
        print_console("error", f"Conflict detected: {', '.join(exc.conflicts)}", stream=sys.stderr)
        for path in exc.conflicts:
            details = exc.details.get(path)
            if details is None:
                continue
            if details.reason:
                print(style_text(details.reason, "yellow", stream=sys.stderr), file=sys.stderr)
            if details.preview:
                print(_format_conflict_preview(details.preview, stream=sys.stderr), file=sys.stderr)
        return 2
    except LeafsyncError as exc:
        print_console("error", str(exc), stream=sys.stderr)
        return 1
    return 0


def _pick_base_url(base_url: str | None, default_base_url: str, project_hint: str | None = None) -> str:
    if project_hint:
        if project_hint.startswith("https://cn.overleaf.com/"):
            return "https://cn.overleaf.com"
        if project_hint.startswith("https://www.overleaf.com/"):
            return "https://www.overleaf.com"
    chosen = (base_url or default_base_url).rstrip("/")
    if chosen not in SUPPORTED_BASE_URLS:
        raise ProjectError(f"Unsupported base URL: {chosen}")
    return chosen


def _make_client(
    base_url: str,
    auth_manager: AuthManager,
    client_factory: ClientFactory | None,
) -> OverleafClientProtocol:
    if client_factory is not None:
        return client_factory(base_url)
    session = auth_manager.load(base_url)
    return OverleafClient(base_url, session=session)


def _load_engine(
    project_dir: Path,
    ignore_file: str,
    auth_manager: AuthManager,
    client_factory: ClientFactory | None,
) -> SyncEngine:
    metadata = ProjectMetadataStore(project_dir.resolve())
    project = metadata.load_project()
    client = _make_client(project.base_url, auth_manager, client_factory)
    return SyncEngine(project_dir.resolve(), client, ignore_file=ignore_file)


def _slugify(name: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in name.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "leaflink-project"


def _resolve_clone_inputs(project_parts: Sequence[str], explicit_target_dir: Path | None) -> tuple[str, Path | None]:
    if explicit_target_dir is not None:
        return " ".join(project_parts).strip(), explicit_target_dir
    if len(project_parts) > 1 and _looks_like_project_reference(project_parts[0]):
        return project_parts[0], Path(" ".join(project_parts[1:]))
    return " ".join(project_parts).strip(), None


def _looks_like_project_reference(value: str) -> bool:
    candidate = value.strip()
    return (
        candidate.startswith("http://")
        or candidate.startswith("https://")
        or (candidate.isalnum() and len(candidate) >= 12)
    )


def _print_status(report: SyncReport) -> None:
    for label, changes in (("local", report.local_changes), ("remote", report.remote_changes)):
        print(f"{_format_label(label)} added: {', '.join(changes.added) or '-'}")
        print(f"{_format_label(label)} modified: {', '.join(changes.modified) or '-'}")
        print(f"{_format_label(label)} deleted: {', '.join(changes.deleted) or '-'}")
    print(f"{_format_label('conflict', text='[conflicts]')} {', '.join(report.conflicts) or '-'}")


def _print_project_list(projects: Sequence[object]) -> None:
    rows = [
        (
            str(getattr(project, "name", "")),
            str(getattr(project, "project_id", "")),
            str(getattr(project, "updated_at", "") or "-"),
        )
        for project in projects
    ]
    headers = ("Name", "Project ID", "Updated")
    project_id_width = max(_display_width(headers[1]), *(_display_width(row[1]) for row in rows))
    updated_width = max(_display_width(headers[2]), *(_display_width(row[2]) for row in rows))
    terminal_width = shutil.get_terminal_size(fallback=(120, 24)).columns
    reserved_width = project_id_width + updated_width + 4
    desired_name_width = max(_display_width(headers[0]), *(_display_width(row[0]) for row in rows))
    max_name_width = max(20, terminal_width - reserved_width)
    name_width = min(desired_name_width, max_name_width)

    print(
        f"{_style_text(_pad_display(headers[0], name_width), 'bold')}  "
        f"{_style_text(_pad_display(headers[1], project_id_width), 'bold')}  "
        f"{_style_text(_pad_display(headers[2], updated_width), 'bold')}"
    )
    print(
        f"{_style_text('-' * name_width, 'dim')}  "
        f"{_style_text('-' * project_id_width, 'dim')}  "
        f"{_style_text('-' * updated_width, 'dim')}"
    )
    for name, project_id, updated in rows:
        print(
            f"{_pad_display(_truncate_display(name, name_width), name_width)}  "
            f"{_pad_display(project_id, project_id_width)}  "
            f"{_pad_display(updated, updated_width)}"
        )


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _pad_display(text: str, width: int) -> str:
    padding = max(0, width - _display_width(text))
    return text + (" " * padding)


def _truncate_display(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    ellipsis = "…"
    target_width = width - _display_width(ellipsis)
    pieces: list[str] = []
    current_width = 0
    for char in text:
        char_width = _display_width(char)
        if current_width + char_width > target_width:
            break
        pieces.append(char)
        current_width += char_width
    return "".join(pieces) + ellipsis


def _print_sync_report(report: SyncReport, prefix: str) -> None:
    if report.merged:
        for path in report.merged:
            _print_sync_line("merge", f"reconciled: {path}")
    if report.pulled:
        for path in report.pulled:
            _print_sync_line(prefix, f"updated: {path}{_format_change_suffix(report.remote_details.get(path))}")
    if report.pushed:
        for path in report.pushed:
            _print_sync_line(prefix, f"uploaded: {path}{_format_change_suffix(report.local_details.get(path))}")
    if not report.pulled and not report.pushed:
        _print_sync_line(prefix, "no changes applied")
    if report.conflicts:
        for path in report.conflicts:
            _print_sync_line("conflict", path)
            details = report.conflict_details.get(path)
            if details is not None:
                if details.reason:
                    print(_style_text(details.reason, "yellow"))
                if details.preview:
                    print(_format_conflict_preview(details.preview))


def _print_sync_event(event: object) -> None:
    if isinstance(event, SyncLifecycleEvent):
        _print_sync_line("sync", event.message, when=event.occurred_at)
        return
    if isinstance(event, LocalChangeEvent):
        _print_sync_line("local", f"modified: {event.path}{_format_change_suffix(ChangeDetails(path=event.path, changed_at=event.changed_at))}")
        return
    if isinstance(event, tuple):
        label, path = event
        _print_sync_line(str(label), f"modified: {path}")
        return
    if isinstance(event, SyncReport):
        for path in event.remote_changes.added + event.remote_changes.modified:
            _print_sync_line("remote", f"changed: {path}{_format_change_suffix(event.remote_details.get(path))}")
        for path in event.remote_changes.deleted:
            _print_sync_line("remote", f"deleted: {path}")
        for path in event.pulled:
            _print_sync_line("pull", f"updated: {path}{_format_change_suffix(event.remote_details.get(path))}")
        for path in event.pushed:
            _print_sync_line("push", f"uploaded: {path}{_format_change_suffix(event.local_details.get(path))}")
        for path in event.conflicts:
            _print_sync_line("conflict", path)
            details = event.conflict_details.get(path)
            if details is not None:
                if details.reason:
                    print(_style_text(details.reason, "yellow"))
                if details.preview:
                    print(_format_conflict_preview(details.preview))


def _format_change_suffix(details: ChangeDetails | None) -> str:
    if details is None:
        return ""
    parts: list[str] = []
    changed_at = format_display_time(details.changed_at)
    if changed_at:
        parts.append(f"saved {changed_at}")
    if details.changed_by:
        parts.append(f"by {details.changed_by}")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def _print_sync_line(label: str, message: str, when: str | None = None) -> None:
    display_time = format_display_time(when or utc_now_iso()) or (when or "")
    print(f"{_style_text(f'[{display_time}]', 'dim')} {_format_label(label)} {message}")


def _interactive_conflict_resolver(path: str, analysis: MergeAnalysis) -> ConflictStrategy:
    print("")
    _print_sync_line("conflict", f"{path}")
    if analysis.reason:
        print(_style_text(analysis.reason, "yellow"))
    if analysis.preview:
        print(_format_conflict_preview(analysis.preview))
    print(_style_text("Choose a resolution:", "bold"))
    print(f"{_style_text('1.', 'green')} keep remote")
    print(f"{_style_text('2.', 'green')} keep local")
    print(f"{_style_text('3.', 'green')} duplicate both")
    while True:
        choice = input(f"{_style_text('>', 'cyan')} ").strip()
        if choice == "1":
            return "keep-remote"
        if choice == "2":
            return "keep-local"
        if choice == "3":
            return "duplicate-both"
        print(_style_text("Enter 1, 2, or 3.", "yellow"))


def _format_conflict_preview(preview: str, context_lines: int = 2, stream: object | None = None) -> str:
    lines = preview.splitlines()
    if not lines:
        return preview
    if not any(line.startswith("<<<<<<<") for line in lines):
        return preview

    selected: list[str] = []
    conflict_start = 0
    while conflict_start < len(lines):
        while conflict_start < len(lines) and not lines[conflict_start].startswith("<<<<<<<"):
            conflict_start += 1
        if conflict_start >= len(lines):
            break

        block_start = max(0, conflict_start - context_lines)
        conflict_end = conflict_start
        while conflict_end < len(lines) and not lines[conflict_end].startswith(">>>>>>>"):
            conflict_end += 1
        block_end = min(len(lines), conflict_end + 1 + context_lines)

        if selected and selected[-1] != "...":
            selected.append("...")
        selected.extend(lines[block_start:block_end])
        conflict_start = block_end

    return "\n".join(_style_conflict_line(line, stream=stream) for line in selected)


def _style_conflict_line(line: str, stream: object | None = None) -> str:
    if line == "...":
        return _style_text(line, "dim", stream=stream)
    if line.startswith("<<<<<<<"):
        return _style_text(line, "green", stream=stream)
    if line.startswith("|||||||"):
        return _style_text(line, "yellow", stream=stream)
    if line.startswith("======="):
        return _style_text(line, "magenta", stream=stream)
    if line.startswith(">>>>>>>"):
        return _style_text(line, "red", stream=stream)
    return line


def _format_label(label: str, text: str | None = None) -> str:
    return format_label(label, text=text)


def _style_text(text: str, style: str, stream: object | None = None) -> str:
    return style_text(text, style, stream=stream if hasattr(stream, "isatty") else None)


def _use_color() -> bool:
    return use_color()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

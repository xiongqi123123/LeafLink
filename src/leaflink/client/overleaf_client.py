"""Best-effort Overleaf client with a clean interface for future extension."""

from __future__ import annotations

import io
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Protocol

from leaflink.client.models import (
    AuthSession,
    DownloadedArchive,
    ProjectInfo,
    ProjectSummary,
    RemoteEntity,
    RemoteFile,
    RemoteProjectSnapshot,
    RemoteProjectTree,
)
from leaflink.client.playwright_bridge import load_project_tree_from_browser
from leaflink.exceptions import AuthenticationError, ClientError
from leaflink.utils.hashing import sha256_bytes

_PROJECT_URL_RE = re.compile(r"^https?://[^/]+/project/([A-Za-z0-9]+)")
_CSRF_META_RE = re.compile(
    r'<meta[^>]+name=["\']ol-csrfToken["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class OverleafClientProtocol(Protocol):
    def list_projects(self) -> list[ProjectSummary]:
        ...

    def resolve_project(self, project_url_or_id: str) -> ProjectInfo:
        ...

    def get_project_snapshot(self, project_id: str) -> RemoteProjectSnapshot:
        ...

    def download_project_archive(self, project_id: str) -> DownloadedArchive:
        ...

    def upload_file(self, project_id: str, path: str, content: bytes) -> None:
        ...

    def delete_file(self, project_id: str, path: str) -> None:
        ...

    def download_pdf(self, project_id: str) -> bytes:
        ...


class OverleafClient:
    """Overleaf client that reads over HTTP and writes through the documented editor routes."""

    def __init__(self, base_url: str, session: AuthSession | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self._csrf_tokens: dict[str, str] = {}
        self._project_trees: dict[str, RemoteProjectTree] = {}
        if session is None:
            raise AuthenticationError(
                f"No stored session for {self.base_url}. Run `leaflink login --base-url {self.base_url}` first."
            )

    def _request(
        self,
        method: str,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        merged_headers = {
            "Cookie": self.session.cookie_header(),
            "User-Agent": "leaflink/0.1.0",
        }
        if headers:
            merged_headers.update(headers)
        request = urllib.request.Request(url, data=data, headers=merged_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ClientError(
                f"Remote request failed with HTTP {exc.code} for {url}: {body[:200]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ClientError(f"Could not reach {url}: {exc}") from exc

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        response = self._request_json_value(method, url, payload=payload, headers=headers)
        if isinstance(response, dict):
            return response
        return {}

    def _request_json_value(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        body: bytes | None = None
        request_headers = dict(headers or {})
        if payload is not None:
            body = json_dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
            request_headers.setdefault("Accept", "application/json")
        response = self._request(method, url, data=body, headers=request_headers)
        if not response:
            return {}
        return json_loads_any(response)

    def _project_url(self, project_id: str) -> str:
        return f"{self.base_url}/project/{project_id}"

    def _dashboard_url(self) -> str:
        return f"{self.base_url}/project"

    def _project_upload_url(self, project_id: str) -> str:
        return f"{self.base_url}/Project/{project_id}/upload"

    def _project_entities_url(self, project_id: str) -> str:
        return f"{self.base_url}/project/{project_id}/entities"

    def _project_history_url(self, project_id: str) -> str:
        return f"{self.base_url}/project/{project_id}/latest/history"

    def _project_changes_users_url(self, project_id: str) -> str:
        return f"{self.base_url}/project/{project_id}/changes/users"

    def resolve_project(self, project_url_or_id: str) -> ProjectInfo:
        project_ref = project_url_or_id.strip()
        match = _PROJECT_URL_RE.match(project_ref)
        if match:
            project_id = match.group(1)
            known_summary = self._find_project_summary(project_id)
        else:
            known_summary = self._find_project_summary(project_ref)
            project_id = known_summary.project_id if known_summary is not None else project_ref
        page = self._request("GET", self._project_url(project_id)).decode("utf-8", errors="replace")
        extracted_name = self._extract_project_name(page)
        name = known_summary.name if known_summary is not None else (extracted_name or project_id)
        revision = self._extract_revision(page)
        return ProjectInfo(project_id=project_id, name=name, base_url=self.base_url, revision=revision)

    def list_projects(self) -> list[ProjectSummary]:
        projects = self._list_projects_via_api()
        if projects:
            return projects
        projects = self._list_projects_via_user_projects()
        if projects:
            return projects
        return self._list_projects_via_html()

    def download_project_archive(self, project_id: str) -> DownloadedArchive:
        candidates = (
            f"{self._project_url(project_id)}/download/zip",
            f"{self._project_url(project_id)}/download/source",
        )
        last_error: Exception | None = None
        for url in candidates:
            try:
                payload = self._request("GET", url)
                files = self._read_archive(payload)
                return DownloadedArchive(project_id=project_id, project_name=project_id, files=files)
            except Exception as exc:  # pragma: no cover - depends on remote API
                last_error = exc
        raise ClientError(f"Could not download project archive for {project_id}: {last_error}")

    def get_project_snapshot(self, project_id: str) -> RemoteProjectSnapshot:
        archive = self.download_project_archive(project_id)
        history_metadata = self._get_project_history_metadata(project_id)
        files = {
            path: RemoteFile(
                path=path,
                content_hash=sha256_bytes(content),
                size=len(content),
                is_binary=b"\0" in content,
                updated_at=history_metadata.get(path, {}).get("updated_at"),
                updated_by=history_metadata.get(path, {}).get("updated_by"),
            )
            for path, content in archive.files.items()
        }
        info = self.resolve_project(project_id)
        return RemoteProjectSnapshot(
            project_id=project_id,
            project_name=info.name,
            revision=info.revision,
            files=files,
        )

    def get_project_tree(self, project_id: str, force_refresh: bool = False) -> RemoteProjectTree:
        if not force_refresh and project_id in self._project_trees:
            return self._project_trees[project_id]
        tree = load_project_tree_from_browser(self.base_url, self.session, project_id)
        self._project_trees[project_id] = tree
        return tree

    def upload_file(self, project_id: str, path: str, content: bytes) -> None:
        tree = self.get_project_tree(project_id)
        root_folder_id = tree.root_folder_id
        relative_path = Path(path).as_posix()
        name = Path(relative_path).name
        body, content_type = build_multipart_body(
            fields={
                "name": name,
                "relativePath": relative_path,
            },
            file_field="qqfile",
            filename=name,
            content=content,
        )
        csrf_token = self._get_csrf_token(project_id)
        url = f"{self._project_upload_url(project_id)}?folder_id={urllib.parse.quote(root_folder_id)}"
        response = self._request_json(
            "POST",
            url,
            payload=None,
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
                "X-Csrf-Token": csrf_token,
            },
        ) if False else None
        # urllib multipart requests need a raw body rather than JSON helpers.
        raw = self._request(
            "POST",
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
                "X-Csrf-Token": csrf_token,
            },
        )
        parsed = json_loads(raw) if raw else {}
        if parsed.get("success") is not True:
            raise ClientError(f"Upload failed for {path}: {parsed}")
        self._project_trees.pop(project_id, None)

    def delete_file(self, project_id: str, path: str) -> None:
        tree = self.get_project_tree(project_id)
        relative_path = Path(path).as_posix()
        entity = tree.entities.get(relative_path)
        if entity is None:
            return
        csrf_token = self._get_csrf_token(project_id)
        url = f"{self.base_url}/project/{project_id}/{entity.entity_type}/{entity.entity_id}"
        self._request(
            "DELETE",
            url,
            headers={
                "Accept": "application/json",
                "X-Csrf-Token": csrf_token,
            },
        )
        self._project_trees.pop(project_id, None)

    def download_pdf(self, project_id: str) -> bytes:
        candidates = (
            f"{self._project_url(project_id)}/download/pdf",
            f"{self._project_url(project_id)}/output/output.pdf",
        )
        last_error: Exception | None = None
        for url in candidates:
            try:
                payload = self._request("GET", url)
                if payload[:4] == b"%PDF":
                    return payload
            except Exception as exc:  # pragma: no cover - depends on remote API
                last_error = exc
        raise ClientError(
            f"No downloadable PDF is available for {project_id}. "
            f"Make sure the project compiles successfully in Overleaf. Last error: {last_error}"
        )

    @staticmethod
    def _extract_project_name(html: str) -> str | None:
        for pattern in (
            r'"name"\s*:\s*"([^"]+)"',
            r"<title>\s*([^<]+?)\s*(?:\||-)\s*Overleaf",
        ):
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return unescape(match.group(1).strip())
        return None

    @staticmethod
    def _extract_revision(html: str) -> str | None:
        for pattern in (
            r'"lastUpdated"\s*:\s*"([^"]+)"',
            r'"revision"\s*:\s*"([^"]+)"',
        ):
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _read_archive(payload: bytes) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            file_infos = [info for info in archive.infolist() if not info.is_dir()]
            common_root = _detect_archive_common_root(file_infos)
            for info in file_infos:
                parts = Path(info.filename).parts
                if common_root is not None and parts and parts[0] == common_root:
                    rel_parts = parts[1:]
                else:
                    rel_parts = parts
                if not rel_parts:
                    continue
                rel_path = Path(*rel_parts).as_posix()
                files[rel_path] = archive.read(info)
        return files

    def _get_csrf_token(self, project_id: str) -> str:
        if project_id in self._csrf_tokens:
            return self._csrf_tokens[project_id]
        html = self._request("GET", self._project_url(project_id)).decode("utf-8", errors="replace")
        match = _CSRF_META_RE.search(html)
        if not match:
            raise ClientError(
                "Could not find the Overleaf CSRF token in the project page. "
                "Please make sure the session is valid and the editor can load in a browser."
            )
        token = unescape(match.group(1))
        self._csrf_tokens[project_id] = token
        return token

    def _get_dashboard_csrf_token(self) -> str:
        key = "__dashboard__"
        if key in self._csrf_tokens:
            return self._csrf_tokens[key]
        html = self._request("GET", self._dashboard_url()).decode("utf-8", errors="replace")
        match = _CSRF_META_RE.search(html)
        if not match:
            raise ClientError(
                "Could not find the Overleaf CSRF token in the dashboard page."
            )
        token = unescape(match.group(1))
        self._csrf_tokens[key] = token
        return token

    def _list_projects_via_api(self) -> list[ProjectSummary]:
        try:
            payload = self._request_json(
                "POST",
                f"{self.base_url}/api/project",
                payload={
                    "filters": {},
                    "sort": {"by": "lastUpdated", "order": "desc"},
                    "page": {"size": 1000},
                },
                headers={
                    "Accept": "application/json",
                    "X-Csrf-Token": self._get_dashboard_csrf_token(),
                },
            )
        except ClientError:
            return []
        raw_projects = payload.get("projects", [])
        if not isinstance(raw_projects, list):
            return []
        projects: list[ProjectSummary] = []
        for item in raw_projects:
            if not isinstance(item, dict):
                continue
            project_id = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            if not project_id or not name:
                continue
            updated_at = item.get("lastUpdated")
            projects.append(
                ProjectSummary(
                    project_id=project_id,
                    name=name,
                    updated_at=str(updated_at) if updated_at else None,
                )
            )
        return projects

    def _list_projects_via_user_projects(self) -> list[ProjectSummary]:
        try:
            payload = self._request_json(
                "GET",
                f"{self.base_url}/user/projects",
                headers={"Accept": "application/json"},
            )
        except ClientError:
            return []
        raw_projects = payload.get("projects", [])
        if not isinstance(raw_projects, list):
            return []
        projects: list[ProjectSummary] = []
        for item in raw_projects:
            if not isinstance(item, dict):
                continue
            project_id = str(item.get("_id", "")).strip()
            name = str(item.get("name", "")).strip()
            if not project_id or not name:
                continue
            projects.append(ProjectSummary(project_id=project_id, name=name))
        return projects

    def _list_projects_via_html(self) -> list[ProjectSummary]:
        html = self._request("GET", self._dashboard_url()).decode("utf-8", errors="replace")
        projects: dict[str, ProjectSummary] = {}
        for match in re.finditer(
            r'href="/project/([A-Za-z0-9]+)"[^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            project_id = match.group(1)
            text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if not text:
                text = project_id
            projects[project_id] = ProjectSummary(project_id=project_id, name=unescape(text))
        return sorted(projects.values(), key=lambda item: item.name.lower())

    def _find_project_summary(self, project_ref: str) -> ProjectSummary | None:
        ref = project_ref.strip()
        if not ref:
            return None
        projects = self.list_projects()
        by_id = {project.project_id: project for project in projects}
        if ref in by_id:
            return by_id[ref]

        exact_name_matches = [project for project in projects if project.name == ref]
        if len(exact_name_matches) == 1:
            return exact_name_matches[0]
        if len(exact_name_matches) > 1:
            raise ClientError(
                f"Multiple projects are named '{ref}'. Please clone by project id or full project URL instead."
            )

        casefold_matches = [project for project in projects if project.name.casefold() == ref.casefold()]
        if len(casefold_matches) == 1:
            return casefold_matches[0]
        if len(casefold_matches) > 1:
            raise ClientError(
                f"Multiple projects match '{ref}'. Please clone by project id or full project URL instead."
            )
        return None

    def _get_project_history_metadata(self, project_id: str) -> dict[str, dict[str, str]]:
        user_names = self._get_change_user_names(project_id)
        try:
            payload = self._request_json(
                "GET",
                self._project_history_url(project_id),
                headers={"Accept": "application/json"},
            )
        except ClientError:
            return {}

        chunk = payload.get("chunk")
        if not isinstance(chunk, dict):
            return {}
        history = chunk.get("history")
        if not isinstance(history, dict):
            return {}
        changes = history.get("changes")
        if not isinstance(changes, list):
            return {}

        metadata: dict[str, dict[str, str]] = {}
        for change in changes:
            if not isinstance(change, dict):
                continue
            updated_at = _normalize_history_timestamp(change.get("timestamp"))
            updated_by = _format_change_actor(change, user_names)
            operations = change.get("operations")
            if not isinstance(operations, list):
                continue
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                pathname = str(operation.get("pathname", "")).strip().lstrip("/")
                if not pathname:
                    continue
                current = metadata.get(pathname)
                if current is None or _history_timestamp_rank(updated_at) >= _history_timestamp_rank(current.get("updated_at")):
                    entry: dict[str, str] = {}
                    if updated_at:
                        entry["updated_at"] = updated_at
                    if updated_by:
                        entry["updated_by"] = updated_by
                    metadata[pathname] = entry
        return metadata

    def _get_change_user_names(self, project_id: str) -> dict[str, str]:
        try:
            payload = self._request_json_value(
                "GET",
                self._project_changes_users_url(project_id),
                headers={"Accept": "application/json"},
            )
        except ClientError:
            return {}

        raw_users = payload if isinstance(payload, list) else payload.get("users", []) if isinstance(payload, dict) else []
        if not isinstance(raw_users, list):
            return {}

        users: dict[str, str] = {}
        for item in raw_users:
            if not isinstance(item, dict):
                continue
            user_id = str(item.get("user_id") or item.get("_id") or item.get("id") or "").strip()
            if not user_id:
                continue
            name = _format_user_name(item)
            if name:
                users[user_id] = name
        return users


def build_multipart_body(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content: bytes,
) -> tuple[bytes, str]:
    boundary = f"leaflink-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def push(text: str) -> None:
        chunks.append(text.encode("utf-8"))

    for key, value in fields.items():
        push(f"--{boundary}\r\n")
        push(f'Content-Disposition: form-data; name="{key}"\r\n\r\n')
        push(f"{value}\r\n")

    push(f"--{boundary}\r\n")
    push(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
    )
    push("Content-Type: application/octet-stream\r\n\r\n")
    chunks.append(content)
    push("\r\n")
    push(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def json_loads(payload: bytes) -> dict[str, object]:
    import json

    return json.loads(payload.decode("utf-8"))


def json_loads_any(payload: bytes) -> object:
    import json

    return json.loads(payload.decode("utf-8"))


def json_dumps(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload)


def _normalize_history_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _history_timestamp_rank(value: str | None) -> float:
    if not value:
        return float("-inf")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return float("-inf")


def _format_change_actor(change: dict[str, object], user_names: dict[str, str]) -> str | None:
    author_ids: list[str] = []
    for key in ("authors", "v2Authors"):
        raw_authors = change.get(key)
        if not isinstance(raw_authors, list):
            continue
        for author in raw_authors:
            author_id = str(author).strip()
            if author_id and author_id not in author_ids:
                author_ids.append(author_id)
    if not author_ids:
        return None

    names = [user_names.get(author_id) for author_id in author_ids if user_names.get(author_id)]
    if names:
        return ", ".join(names)
    return None


def _format_user_name(payload: dict[str, object]) -> str | None:
    first_name = str(payload.get("first_name") or "").strip()
    last_name = str(payload.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if full_name:
        return full_name
    for key in ("name", "email"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _detect_archive_common_root(file_infos: list[zipfile.ZipInfo]) -> str | None:
    first_parts = []
    for info in file_infos:
        parts = Path(info.filename).parts
        if len(parts) < 2:
            return None
        first_parts.append(parts[0])
    if not first_parts:
        return None
    common_root = first_parts[0]
    if any(part != common_root for part in first_parts):
        return None
    return common_root

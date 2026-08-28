from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any

from markupsafe import Markup

from .bundle_reader import DocumentBundleReader
from .bundles import DocumentBundleManager
from .paths import safe_instance_path
from .storage import InstanceStore

# A bundle may contain the full two-million-character extracted-text allowance plus
# deterministic headings, page labels and asset references.
MAX_VIEWER_MARKDOWN_CHARS = 2_500_000
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
MARKDOWN_MEDIA_TYPES = frozenset(
    {
        "text/markdown",
        "text/x-markdown",
    }
)
_INLINE_LINK = re.compile(
    r"(!?)\[([^\]\n]{0,500})\]\(([^)\n]{0,2000})\)"
)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_STRONG = re.compile(r"\*\*([^*\n]+)\*\*")
_EMPHASIS = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_UNORDERED = re.compile(r"^[ \t]{0,3}[-+*][ \t]+(.+?)\s*$")
_ORDERED = re.compile(r"^[ \t]{0,3}\d+[.)][ \t]+(.+?)\s*$")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(?:[ \t].*)?$")


class DocumentContentError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_inline(value: str) -> str:
    escaped = html.escape(value, quote=True)
    escaped = _INLINE_LINK.sub(
        lambda match: (
            '<span class="blocked-resource">[Image blocked: '
            if match.group(1)
            else '<span class="blocked-link">'
        )
        + match.group(2)
        + ("]</span>" if match.group(1) else "</span>"),
        escaped,
    )
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _STRONG.sub(r"<strong>\1</strong>", escaped)
    return _EMPHASIS.sub(r"<em>\1</em>", escaped)


def safe_markdown_html(value: str) -> Markup:
    """Render a bounded structural Markdown subset without navigable resources."""

    selected = value[:MAX_VIEWER_MARKDOWN_CHARS]
    lines = selected.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    fence: str | None = None
    code_lines: list[str] = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            output.append(f"</{list_kind}>")
            list_kind = None

    def flush_paragraph() -> None:
        if paragraph:
            close_list()
            output.append(f"<p>{' '.join(_safe_inline(line) for line in paragraph)}</p>")
            paragraph.clear()

    for line in lines:
        if fence is not None:
            if line.lstrip().startswith(fence):
                output.append(
                    "<pre><code>"
                    + html.escape("\n".join(code_lines), quote=True)
                    + "</code></pre>"
                )
                code_lines.clear()
                fence = None
            else:
                code_lines.append(line)
            continue

        fence_match = _FENCE.match(line)
        if fence_match:
            flush_paragraph()
            close_list()
            fence = fence_match.group(1)[0] * len(fence_match.group(1))
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_safe_inline(heading.group(2))}</h{level}>")
            continue
        unordered = _UNORDERED.match(line)
        ordered = _ORDERED.match(line)
        if unordered or ordered:
            flush_paragraph()
            selected_kind = "ul" if unordered else "ol"
            if list_kind != selected_kind:
                close_list()
                list_kind = selected_kind
                output.append(f"<{selected_kind}>")
            match = unordered or ordered
            output.append(f"<li>{_safe_inline(match.group(1))}</li>")
            continue
        if line.startswith(">"):
            flush_paragraph()
            close_list()
            output.append(f"<blockquote>{_safe_inline(line[1:].lstrip())}</blockquote>")
            continue
        paragraph.append(line.strip())

    if fence is not None:
        output.append(
            "<pre><code>"
            + html.escape("\n".join(code_lines), quote=True)
            + "</code></pre>"
        )
    flush_paragraph()
    close_list()
    return Markup("\n".join(output))


class DocumentContentReader:
    """Expose verified local document representations without implicit writes."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.bundles = DocumentBundleReader(store)

    @staticmethod
    def _is_markdown(document: dict[str, Any], version: dict[str, Any]) -> bool:
        return (
            str(version.get("media_type", "")).casefold() in MARKDOWN_MEDIA_TYPES
            or Path(str(document.get("locator", ""))).suffix.casefold()
            in MARKDOWN_SUFFIXES
        )

    def _verified_original(
        self,
        version: dict[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        original = self.store.read_canonical("originals", str(version["original_id"]))
        if original is None:
            raise DocumentContentError("current DocumentVersion has no Original")
        try:
            path = safe_instance_path(self.store.paths.root, str(original["storage_ref"]))
            data = path.read_bytes()
        except (KeyError, OSError, ValueError) as exc:
            raise DocumentContentError("current Original cannot be read safely") from exc
        if (
            _sha256(data) != original.get("sha256")
            or _sha256(data) != version.get("content_hash")
            or len(data) != original.get("size_bytes")
            or len(data) != version.get("size_bytes")
        ):
            raise DocumentContentError("current Original failed hash or size verification")
        return original, data

    def _extracted_markdown(
        self,
        document: dict[str, Any],
        version: dict[str, Any],
    ) -> str | None:
        artifact = self.store.derived_artifact_for_version(
            str(version["id"]),
            "extracted_text",
        )
        if artifact is None:
            return None
        try:
            path = safe_instance_path(self.store.paths.root, str(artifact["storage_ref"]))
            data = path.read_bytes()
            text = data.decode("utf-8")
        except (KeyError, OSError, UnicodeError, ValueError):
            return None
        if _sha256(data) != artifact.get("checksum"):
            return None
        title = str(document.get("title") or "Untitled document").replace("\n", " ")
        return f"# {title}\n\n{text.rstrip()}\n"

    def verified_original(self, document_id: str) -> dict[str, Any] | None:
        """Read one current Original and verify every canonical byte binding."""

        document = self.store.read_canonical("documents", document_id)
        if document is None:
            return None
        version = self.store.read_canonical(
            "versions",
            str(document["current_version_id"]),
        )
        if version is None:
            raise DocumentContentError("Document has no readable current Version")
        original, data = self._verified_original(version)
        return {
            "document": document,
            "version": version,
            "original": original,
            "data": data,
        }

    @staticmethod
    def _bounded(value: str | None, max_chars: int) -> tuple[str | None, bool]:
        if value is None:
            return None, False
        return value[:max_chars], len(value) > max_chars

    def get(
        self,
        document_id: str,
        *,
        max_chars: int = MAX_VIEWER_MARKDOWN_CHARS,
        build_missing_bundle: bool = False,
    ) -> dict[str, Any] | None:
        if max_chars < 1 or max_chars > MAX_VIEWER_MARKDOWN_CHARS:
            raise ValueError("document content limit is outside the supported range")
        verified = self.verified_original(document_id)
        if verified is None:
            return None
        document = verified["document"]
        version = verified["version"]
        original = verified["original"]
        original_bytes = verified["data"]
        text_original = None
        if self._is_markdown(document, version) or str(
            version.get("media_type", "")
        ).startswith("text/"):
            try:
                text_original = original_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text_original = None

        source = "unavailable"
        raw_markdown = None
        bundle = None
        if self._is_markdown(document, version) and text_original is not None:
            raw_markdown = text_original
            source = "verified_original_markdown"
        else:
            bundle = self.bundles.get(str(version["id"]))
            if bundle is None and build_missing_bundle:
                DocumentBundleManager(self.store).build_version(str(version["id"]))
                bundle = self.bundles.get(str(version["id"]))
            if bundle is not None:
                raw_markdown = self.bundles.read_markdown(str(version["id"]))
                source = "verified_document_bundle"
            if raw_markdown is None:
                raw_markdown = self._extracted_markdown(document, version)
                if raw_markdown is not None:
                    source = "verified_extracted_text"

        selected_markdown, markdown_truncated = self._bounded(raw_markdown, max_chars)
        selected_original, original_truncated = self._bounded(text_original, max_chars)
        return {
            "document_id": document_id,
            "version_id": str(version["id"]),
            "media_type": str(version["media_type"]),
            "source": source,
            "markdown": selected_markdown,
            "markdown_truncated": markdown_truncated,
            "original_text": selected_original,
            "original_text_truncated": original_truncated,
            "original": {
                "id": str(original["id"]),
                "storage_ref": str(original["storage_ref"]),
                "sha256": str(original["sha256"]),
                "size_bytes": int(original["size_bytes"]),
            },
            "bundle": bundle,
        }

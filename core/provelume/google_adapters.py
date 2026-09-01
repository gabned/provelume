from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .connector_model import normalise_secret_reference
from .google_contract import (
    GOOGLE_ADAPTER_ID,
    GOOGLE_ADAPTER_PROTOCOL_VERSION,
    GOOGLE_ADAPTER_VERSION,
    GOOGLE_ALLOWED_ORIGINS,
    GOOGLE_NATIVE_EXPORTS,
    GoogleAdapterError,
    GoogleAuthorizationError,
    GoogleContractError,
    GoogleItem,
    GoogleLimits,
    GooglePage,
    GoogleRateLimitError,
    normalise_capability,
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _environment_secret(reference: Mapping[str, str]) -> str:
    selected = normalise_secret_reference(reference)
    if selected is None:
        raise GoogleAuthorizationError()
    if selected["kind"] == "environment":
        value = os.environ.get(selected["name"])
        if not isinstance(value, str) or not value.strip():
            raise GoogleAuthorizationError(expired=True)
        return value.strip()
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GoogleAuthorizationError() from exc
    value = keyring.get_password("provelume", selected["name"])
    if not isinstance(value, str) or not value.strip():
        raise GoogleAuthorizationError(expired=True)
    return value.strip()


class UnavailableGoogleAdapter:
    adapter_id = GOOGLE_ADAPTER_ID
    adapter_version = GOOGLE_ADAPTER_VERSION
    adapter_protocol_version = GOOGLE_ADAPTER_PROTOCOL_VERSION

    def fetch_page(
        self,
        *,
        instance: Mapping[str, Any],
        capability: Mapping[str, Any],
        source: Mapping[str, Any],
        cursor: str | None,
        limits: GoogleLimits,
    ) -> GooglePage:
        del instance, capability, source, cursor, limits
        raise GoogleAdapterError(
            "google_adapter_unavailable",
            "No Google provider adapter has been selected",
        )


class SyntheticGoogleAdapter:
    """Deterministic adapter for public CI; it never reads credentials or opens a socket."""

    adapter_id = GOOGLE_ADAPTER_ID
    adapter_version = GOOGLE_ADAPTER_VERSION
    adapter_protocol_version = GOOGLE_ADAPTER_PROTOCOL_VERSION

    def __init__(
        self,
        pages: Mapping[str, Sequence[GooglePage]],
        *,
        fail_at: Mapping[str, Mapping[int, GoogleContractError]] | None = None,
    ):
        self._pages = {key: tuple(value) for key, value in pages.items()}
        self._fail_at = {key: dict(value) for key, value in (fail_at or {}).items()}
        self.calls: list[dict[str, Any]] = []

    def fetch_page(
        self,
        *,
        instance: Mapping[str, Any],
        capability: Mapping[str, Any],
        source: Mapping[str, Any],
        cursor: str | None,
        limits: GoogleLimits,
    ) -> GooglePage:
        del instance, capability
        source_id = str(source["source_id"])
        index = 0 if cursor is None else int(cursor)
        self.calls.append({"source_id": source_id, "page": index})
        failure = self._fail_at.get(source_id, {}).get(index)
        if failure is not None:
            raise failure
        pages = self._pages.get(source_id, ())
        if index >= len(pages):
            return GooglePage(capability=source["capability"], items=())
        page = pages[index]
        if len(page.items) > limits.max_items_per_page:
            raise GoogleAdapterError(
                "google_payload_limit_exceeded",
                "Synthetic Google page exceeds the configured item limit",
            )
        expected_cursor = str(index + 1) if index + 1 < len(pages) else None
        return GooglePage(
            capability=page.capability,
            items=page.items,
            next_cursor=expected_cursor,
        )


class GoogleApiAdapter:
    """Bounded Google REST preview adapter.

    This adapter is deliberately dependency-light and unqualified without an exact-head,
    separately authorized authenticated smoke. Credential values are resolved transiently and
    are never returned in an exception, result, receipt or durable record.
    """

    adapter_id = GOOGLE_ADAPTER_ID
    adapter_version = GOOGLE_ADAPTER_VERSION
    adapter_protocol_version = GOOGLE_ADAPTER_PROTOCOL_VERSION

    def __init__(
        self,
        *,
        credential_resolver: Callable[[Mapping[str, str]], str] = _environment_secret,
    ):
        self._credential_resolver = credential_resolver
        self._opener = build_opener(_NoRedirect())

    @staticmethod
    def _safe_endpoint(url: str) -> None:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme != "https" or origin not in GOOGLE_ALLOWED_ORIGINS:
            raise GoogleAdapterError(
                "google_payload_invalid", "Google adapter endpoint is outside the allowlist"
            )

    def _request(
        self,
        url: str,
        *,
        credential_reference: Mapping[str, str],
        limits: GoogleLimits,
        maximum: int,
    ) -> tuple[bytes, str | None]:
        self._safe_endpoint(url)
        credential = self._credential_resolver(credential_reference)
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json, message/rfc822, application/octet-stream",
                "Authorization": f"Bearer {credential}",
                "User-Agent": "Provelume/0.8 Google-readonly-preview",
            },
        )
        try:
            with self._opener.open(request, timeout=limits.request_timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as exc:
                        raise GoogleAdapterError(
                            "google_payload_invalid", "Google response length is invalid"
                        ) from exc
                    if declared < 0 or declared > maximum:
                        raise GoogleAdapterError(
                            "google_payload_limit_exceeded",
                            "Google response exceeds the configured byte limit",
                        )
                payload = response.read(maximum + 1)
                if len(payload) > maximum:
                    raise GoogleAdapterError(
                        "google_payload_limit_exceeded",
                        "Google response exceeds the configured byte limit",
                    )
                return payload, content_type
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise GoogleAuthorizationError(expired=True) from exc
            if exc.code == 429:
                retry = exc.headers.get("Retry-After")
                retry_after = int(retry) if retry and retry.isdigit() else None
                raise GoogleRateLimitError(retry_after_seconds=retry_after) from exc
            if 500 <= exc.code <= 599:
                raise GoogleAdapterError(
                    "google_retryable_failure", "Google provider returned a retryable failure"
                ) from exc
            raise GoogleAdapterError(
                "google_payload_invalid", "Google provider rejected the bounded read request"
            ) from exc
        except (TimeoutError, URLError) as exc:
            raise GoogleAdapterError(
                "google_retryable_failure", "Google provider request failed transiently"
            ) from exc

    def _json(
        self,
        url: str,
        *,
        credential_reference: Mapping[str, str],
        limits: GoogleLimits,
    ) -> dict[str, Any]:
        payload, content_type = self._request(
            url,
            credential_reference=credential_reference,
            limits=limits,
            maximum=limits.max_json_bytes,
        )
        if content_type != "application/json":
            raise GoogleAdapterError(
                "google_payload_invalid", "Google metadata response is not JSON"
            )
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GoogleAdapterError(
                "google_payload_invalid", "Google metadata response is malformed"
            ) from exc
        if not isinstance(value, dict):
            raise GoogleAdapterError(
                "google_payload_invalid", "Google metadata response must be an object"
            )
        return value

    @staticmethod
    def _reference(capability: Mapping[str, Any]) -> Mapping[str, str]:
        reference = normalise_secret_reference(capability.get("credential_reference"))
        if reference is None:
            raise GoogleAuthorizationError()
        return reference

    def _gmail_page(
        self,
        *,
        capability: Mapping[str, Any],
        source: Mapping[str, Any],
        cursor: str | None,
        limits: GoogleLimits,
    ) -> GooglePage:
        params: list[tuple[str, str | int]] = [
            ("maxResults", limits.max_items_per_page),
        ]
        if cursor is not None:
            params.append(("pageToken", cursor))
        if source["selection_kind"] == "label":
            params.extend(("labelIds", value) for value in source["selectors"])
        listing = self._json(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?"
            + urlencode(params, doseq=True),
            credential_reference=self._reference(capability),
            limits=limits,
        )
        rows = listing.get("messages", [])
        if not isinstance(rows, list) or len(rows) > limits.max_items_per_page:
            raise GoogleAdapterError(
                "google_payload_limit_exceeded", "Gmail message page exceeds its closed limit"
            )
        items: list[GoogleItem] = []
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
                raise GoogleAdapterError(
                    "google_payload_invalid", "Gmail message reference is malformed"
                )
            message_id = row["id"]
            value = self._json(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                + quote(message_id, safe="")
                + "?format=raw",
                credential_reference=self._reference(capability),
                limits=limits,
            )
            raw = value.get("raw")
            if not isinstance(raw, str) or len(raw) > (limits.max_item_bytes * 4 // 3 + 16):
                raise GoogleAdapterError(
                    "google_payload_limit_exceeded", "Gmail raw message exceeds its closed limit"
                )
            try:
                payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            except (ValueError, TypeError) as exc:
                raise GoogleAdapterError(
                    "google_payload_invalid", "Gmail raw message encoding is invalid"
                ) from exc
            if not payload or len(payload) > limits.max_item_bytes:
                raise GoogleAdapterError(
                    "google_payload_limit_exceeded", "Gmail raw message exceeds its closed limit"
                )
            thread_id = value.get("threadId")
            labels = value.get("labelIds", [])
            internal_date = value.get("internalDate")
            observed = None
            if isinstance(internal_date, str) and internal_date.isdigit():
                from datetime import UTC, datetime

                observed = datetime.fromtimestamp(int(internal_date) / 1000, UTC).isoformat()
            items.append(
                GoogleItem(
                    capability="gmail",
                    provider_item_id=message_id,
                    provider_revision_id=str(value.get("historyId") or message_id),
                    payload=payload,
                    media_type="message/rfc822",
                    provider_thread_id=thread_id if isinstance(thread_id, str) else None,
                    provider_labels=(
                        tuple(str(item) for item in labels) if isinstance(labels, list) else ()
                    ),
                    provider_observed_at=observed,
                )
            )
        next_cursor = listing.get("nextPageToken")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise GoogleAdapterError("google_payload_invalid", "Gmail page cursor is malformed")
        return GooglePage(capability="gmail", items=tuple(items), next_cursor=next_cursor)

    @staticmethod
    def _drive_query(source: Mapping[str, Any]) -> str:
        def escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace("'", "\\'")

        if source["selection_kind"] == "folder":
            folders = source["selectors"]
            return (
                "("
                + " or ".join(f"'{escape(value)}' in parents" for value in folders)
                + ") and trashed=false"
            )
        files = source["selectors"]
        return "(" + " or ".join(f"id='{escape(value)}'" for value in files) + ") and trashed=false"

    def _drive_metadata(
        self,
        file_id: str,
        *,
        reference: Mapping[str, str],
        limits: GoogleLimits,
    ) -> dict[str, Any]:
        fields = "id,mimeType,modifiedTime,version,headRevisionId,md5Checksum,size"
        return self._json(
            "https://www.googleapis.com/drive/v3/files/"
            + quote(file_id, safe="")
            + "?"
            + urlencode({"fields": fields, "supportsAllDrives": "true"}),
            credential_reference=reference,
            limits=limits,
        )

    def _drive_page(
        self,
        *,
        capability: Mapping[str, Any],
        source: Mapping[str, Any],
        cursor: str | None,
        limits: GoogleLimits,
    ) -> GooglePage:
        reference = self._reference(capability)
        fields = (
            "nextPageToken,files(id,mimeType,modifiedTime,version,headRevisionId,md5Checksum,size)"
        )
        params: dict[str, str | int] = {
            "q": self._drive_query(source),
            "pageSize": limits.max_items_per_page,
            "fields": fields,
            "spaces": "drive",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if cursor is not None:
            params["pageToken"] = cursor
        listing = self._json(
            "https://www.googleapis.com/drive/v3/files?" + urlencode(params),
            credential_reference=reference,
            limits=limits,
        )
        rows = listing.get("files", [])
        if not isinstance(rows, list) or len(rows) > limits.max_items_per_page:
            raise GoogleAdapterError(
                "google_payload_limit_exceeded", "Drive file page exceeds its closed limit"
            )
        items: list[GoogleItem] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise GoogleAdapterError(
                    "google_payload_invalid", "Drive file metadata is malformed"
                )
            file_id = row.get("id")
            media_type = row.get("mimeType")
            if not isinstance(file_id, str) or not isinstance(media_type, str):
                raise GoogleAdapterError(
                    "google_payload_invalid", "Drive file identity is malformed"
                )
            revision = str(row.get("headRevisionId") or row.get("version") or "unknown")
            export_format = GOOGLE_NATIVE_EXPORTS.get(media_type)
            if export_format is None and media_type.startswith("application/vnd.google-apps."):
                raise GoogleAdapterError(
                    "google_payload_invalid", "Drive Google-native format is unsupported"
                )
            if export_format is None:
                url = (
                    "https://www.googleapis.com/drive/v3/files/"
                    + quote(file_id, safe="")
                    + "?alt=media&supportsAllDrives=true"
                )
                effective_type = media_type
                google_native = False
            else:
                url = (
                    "https://www.googleapis.com/drive/v3/files/"
                    + quote(file_id, safe="")
                    + "/export?"
                    + urlencode({"mimeType": export_format})
                )
                effective_type = export_format
                google_native = True
            payload, _content_type = self._request(
                url,
                credential_reference=reference,
                limits=limits,
                maximum=limits.max_item_bytes,
            )
            if not payload:
                raise GoogleAdapterError(
                    "google_payload_invalid", "Drive returned an empty file representation"
                )
            rechecked = self._drive_metadata(file_id, reference=reference, limits=limits)
            rechecked_revision = str(
                rechecked.get("headRevisionId") or rechecked.get("version") or "unknown"
            )
            if rechecked_revision != revision or rechecked.get("mimeType") != media_type:
                raise GoogleAdapterError(
                    "google_remote_mutation", "Drive item changed during bounded acquisition"
                )
            items.append(
                GoogleItem(
                    capability="drive",
                    provider_item_id=file_id,
                    provider_revision_id=revision,
                    payload=payload,
                    media_type=effective_type,
                    provider_observed_at=(
                        row.get("modifiedTime")
                        if isinstance(row.get("modifiedTime"), str)
                        else None
                    ),
                    source_format=media_type if google_native else None,
                    export_format=export_format,
                    google_native=google_native,
                )
            )
        next_cursor = listing.get("nextPageToken")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise GoogleAdapterError("google_payload_invalid", "Drive page cursor is malformed")
        return GooglePage(capability="drive", items=tuple(items), next_cursor=next_cursor)

    def fetch_page(
        self,
        *,
        instance: Mapping[str, Any],
        capability: Mapping[str, Any],
        source: Mapping[str, Any],
        cursor: str | None,
        limits: GoogleLimits,
    ) -> GooglePage:
        del instance
        selected = normalise_capability(capability.get("capability"))
        if selected != source.get("capability"):
            raise GoogleAdapterError(
                "google_payload_invalid", "Google Source capability binding is invalid"
            )
        if selected == "gmail":
            return self._gmail_page(
                capability=capability,
                source=source,
                cursor=cursor,
                limits=limits,
            )
        return self._drive_page(
            capability=capability,
            source=source,
            cursor=cursor,
            limits=limits,
        )


__all__ = [
    "GoogleApiAdapter",
    "SyntheticGoogleAdapter",
    "UnavailableGoogleAdapter",
]

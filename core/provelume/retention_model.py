from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from .storage import InstanceStore

DISPOSITION_SCHEMA_VERSION = 1
DISPOSITION_STATUSES = frozenset({"active", "archived", "trashed"})
LIBRARY_VISIBILITIES = frozenset({"included", "excluded"})
DISPOSITION_FILTERS = frozenset({*DISPOSITION_STATUSES, "all"})
_DOCUMENT_ID = re.compile(r"doc_[0-9a-f]{32}\Z")
_DISPOSITION_ID = re.compile(r"disp_[0-9a-f]{32}\Z")
_OPERATION_ID = re.compile(r"op_[0-9a-f]{32}\Z")


class RetentionError(RuntimeError):
    pass


class RetentionNotFoundError(RetentionError):
    pass


class RetentionConflictError(RetentionError):
    pass


class RetentionIntegrityError(RetentionError):
    pass


class PurgeAuthorizationError(RetentionError):
    pass


class PurgeTransactionError(RetentionError):
    pass


def disposition_id(document_id: str) -> str:
    value = f"provelume:disposition:{DISPOSITION_SCHEMA_VERSION}:{document_id}"
    return f"disp_{uuid5(NAMESPACE_URL, value).hex}"


def default_disposition(document_id: str) -> dict[str, Any]:
    return {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "id": disposition_id(document_id),
        "document_id": document_id,
        "status": "active",
        "library_visibility": "included",
        "restore_status": None,
        "restore_library_visibility": None,
        "revision": 0,
        "created_at": None,
        "updated_at": None,
        "last_operation_id": None,
        "recorded": False,
    }


def disposition_view(value: Mapping[str, Any]) -> dict[str, Any]:
    status = str(value["status"])
    visibility = str(value["library_visibility"])
    return {
        **dict(value),
        "archived": status == "archived",
        "trashed": status == "trashed",
        "projected": status != "trashed" and visibility == "included",
    }


def canonical_disposition_errors(
    dispositions: Mapping[str, Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    expected_keys = {
        "schema_version",
        "id",
        "document_id",
        "status",
        "library_visibility",
        "restore_status",
        "restore_library_visibility",
        "revision",
        "created_at",
        "updated_at",
        "last_operation_id",
    }
    seen_documents: set[str] = set()
    for record_id, value in dispositions.items():
        path = f"knowledge/dispositions/{record_id}.json"
        document_id = value.get("document_id")
        if (
            set(value) != expected_keys
            or value.get("schema_version") != DISPOSITION_SCHEMA_VERSION
            or _DISPOSITION_ID.fullmatch(record_id) is None
            or not isinstance(document_id, str)
            or _DOCUMENT_ID.fullmatch(document_id) is None
            or value.get("id") != record_id
            or disposition_id(document_id) != record_id
        ):
            errors.append(
                (
                    "disposition_record_invalid",
                    "Document disposition identity or schema is invalid",
                    path,
                )
            )
            continue
        if document_id in seen_documents:
            errors.append(
                (
                    "disposition_document_duplicate",
                    "Document has more than one disposition record",
                    path,
                )
            )
        seen_documents.add(document_id)
        if document_id not in documents:
            errors.append(
                (
                    "disposition_document_missing",
                    "Disposition references a missing Document",
                    path,
                )
            )
        status = value.get("status")
        visibility = value.get("library_visibility")
        revision = value.get("revision")
        if (
            status not in DISPOSITION_STATUSES
            or visibility not in LIBRARY_VISIBILITIES
            or type(revision) is not int
            or revision < 1
            or not isinstance(value.get("created_at"), str)
            or not str(value["created_at"]).strip()
            or not isinstance(value.get("updated_at"), str)
            or not str(value["updated_at"]).strip()
            or _OPERATION_ID.fullmatch(str(value.get("last_operation_id", "")))
            is None
        ):
            errors.append(
                (
                    "disposition_state_invalid",
                    "Document disposition state, revision or operation identity is invalid",
                    path,
                )
            )
        restore_status = value.get("restore_status")
        restore_visibility = value.get("restore_library_visibility")
        restore_valid = (
            status == "trashed"
            and restore_status in {"active", "archived"}
            and restore_visibility in LIBRARY_VISIBILITIES
        ) or (
            status != "trashed"
            and restore_status is None
            and restore_visibility is None
        )
        if not restore_valid:
            errors.append(
                (
                    "disposition_restore_state_invalid",
                    "Trash restoration state is invalid",
                    path,
                )
            )
    return errors


def disposition_records(store: InstanceStore) -> dict[str, dict[str, Any]]:
    documents = {
        str(item["id"]): item for item in store.list_canonical("documents")
    }
    raw_records = store.list_canonical("dispositions")
    records = {
        str(item.get("id", "")): item
        for item in raw_records
    }
    if len(records) != len(raw_records):
        raise RetentionIntegrityError("Document disposition identity is duplicated")
    errors = canonical_disposition_errors(records, documents)
    if errors:
        raise RetentionIntegrityError(errors[0][1])
    return {str(item["document_id"]): item for item in records.values()}


def effective_dispositions(store: InstanceStore) -> dict[str, dict[str, Any]]:
    recorded = disposition_records(store)
    return {
        str(document["id"]): disposition_view(
            {
                **recorded.get(
                    str(document["id"]),
                    default_disposition(str(document["id"])),
                ),
                "recorded": str(document["id"]) in recorded,
            }
        )
        for document in store.list_canonical("documents")
    }

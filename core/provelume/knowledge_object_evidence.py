"""Fresh, bounded local evidence resolution; availability never certifies truth."""

from __future__ import annotations

import hashlib
import json
import math
import re

import yaml

from .knowledge_object_contract import KnowledgeObjectError, record_digest, validate_evidence
from .representations import canonical_json_bytes, validate_representation_bundle
from .review_decisions import checked_path

MAX_EVIDENCE_BYTES = 512 * 1024 * 1024
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024


def require(value, code="evidence_unavailable"):
    if not value:
        raise KnowledgeObjectError(code)


def object_path(store, relative):
    try:
        require(
            not any(p.is_symlink() or p.is_junction() for p in store.paths.root.parents),
            "integrity",
        )
        return checked_path(store, relative)
    except KnowledgeObjectError:
        raise
    except (OSError, ValueError):
        raise KnowledgeObjectError("integrity") from None


def current_instance_id(store):
    try:
        object_path(store, "provelume.yml")
        config = store.read_config()
        identity = config["instance"]["id"]
        require(type(config["schema_version"]) is int and config["schema_version"] == 3, "schema")
        require(type(identity) is str and re.fullmatch(r"inst_[0-9a-f]{32}", identity), "integrity")
        return identity
    except KnowledgeObjectError:
        raise
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        raise KnowledgeObjectError("integrity") from None


def bounded_json(path, maximum=MAX_BUNDLE_BYTES):
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            require(depth <= 16 and count <= 32768, "limit")
            if type(item) is dict:
                pending.extend((v, depth + 1) for v in item.values())
            elif type(item) is list:
                pending.extend((v, depth + 1) for v in item)
            elif type(item) is float:
                require(math.isfinite(item))
        require(type(value) is dict)
        return value
    except KnowledgeObjectError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise KnowledgeObjectError("evidence_unavailable") from None


class ObjectEvidenceResolver:
    """One operation's byte budget; no network, derivation, mutation or retargeting."""

    def __init__(self, store):
        self.store = store
        self.remaining = MAX_EVIDENCE_BYTES

    def _record(self, kind, identity, prefix):
        require(type(identity) is str and re.fullmatch(prefix + r"_[0-9a-f]{32}", identity))
        value = bounded_json(object_path(self.store, f"knowledge/{kind}/{identity}.json"))
        require(value.get("id") == identity)
        return value

    def _file(self, relative, size, digest, maximum, *, retain=False):
        require(type(size) is int and 0 <= size <= min(maximum, self.remaining), "limit")
        self.remaining -= size
        path = object_path(self.store, relative)
        require(path.is_file() and path.stat().st_size == size)
        total, fingerprint, pieces = 0, hashlib.sha256(), []
        with path.open("rb") as stream:
            while chunk := stream.read(min(1024 * 1024, size - total + 1)):
                total += len(chunk)
                require(total <= size)
                fingerprint.update(chunk)
                if retain:
                    pieces.append(chunk)
        require(total == size and fingerprint.hexdigest() == digest)
        return b"".join(pieces) if retain else None

    def for_version(self, version_id, *, selector=None):
        try:
            version = self._record("versions", version_id, "ver")
            row = {
                "schema_version": 1,
                "instance_id": current_instance_id(self.store),
                "document_id": version["document_id"],
                "version_id": version_id,
                "original_id": version["original_id"],
                "original_sha256": version["content_hash"],
                "selector": {"kind": "original"} if selector is None else selector,
            }
            row = {**row, "id": "evd_" + record_digest(row)}
            self.resolve(row)
            return row
        except KnowledgeObjectError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise KnowledgeObjectError("evidence_unavailable") from None

    def resolve(self, evidence):
        validate_evidence(evidence)
        require(evidence["instance_id"] == current_instance_id(self.store))
        try:
            version = self._record("versions", evidence["version_id"], "ver")
            document = self._record("documents", evidence["document_id"], "doc")
            require(version["document_id"] == document["id"])
            original = bounded_json(
                object_path(self.store, f"knowledge/originals/{evidence['original_id']}.json")
            )
            require(
                original["id"] == version["original_id"] == evidence["original_id"]
                and original["sha256"] == version["content_hash"] == evidence["original_sha256"]
                and original["size_bytes"] == version["size_bytes"]
            )
            self._file(
                original["storage_ref"],
                original["size_bytes"],
                original["sha256"],
                MAX_EVIDENCE_BYTES,
            )
            selector = evidence["selector"]
            if selector["kind"] == "text":
                self._page(version, original, selector)
            return {"id": evidence["id"], "status": "AVAILABLE", "truth": "NOT_VERIFIED"}
        except KnowledgeObjectError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise KnowledgeObjectError("evidence_unavailable") from None

    def _page(self, version, original, selector):
        rid = selector["representation_id"]
        prefix = f"state/derived/representations/{rid}/"
        bundle = bounded_json(object_path(self.store, prefix + "bundle.json"))
        validate_representation_bundle(bundle)
        require(
            bundle["representation_id"] == rid
            and bundle["version"]
            == {
                "id": version["id"],
                "original_id": original["id"],
                "original_sha256": original["sha256"],
                "original_size_bytes": original["size_bytes"],
            }
        )
        require(
            bundle["lifecycle"]["state"] == "active"
            and bundle["availability"]["state"] == "available"
            and not bundle["corrections"],
            "evidence_unsupported",
        )
        for ordinal, anchor in enumerate(bundle["anchors"]):
            expected = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "representation_id": rid,
                        "ordinal": ordinal,
                        "kind": anchor["kind"],
                        "target": anchor["target"],
                    }
                )
            ).hexdigest()
            require(anchor["id"] == "ranc_" + expected)
        anchors = [a for a in bundle["anchors"] if a["id"] == selector["anchor_id"]]
        outputs = [o for o in bundle["outputs"] if o["id"] == selector["output_id"]]
        require(len(anchors) == len(outputs) == 1)
        anchor, output = anchors[0], outputs[0]
        require(
            anchor["kind"] == "page" and output["media_type"] == "text/plain",
            "evidence_unsupported",
        )
        reference = output["storage_ref"]
        require(
            reference.startswith(prefix + "outputs/")
            and "/" not in reference[len(prefix + "outputs/") :]
        )
        raw = self._file(
            reference, output["size_bytes"], output["sha256"], MAX_TEXT_BYTES, retain=True
        )
        pages = raw.decode("utf-8", errors="strict").split("\f")
        page = anchor["target"]["page"]
        require(1 <= page <= len(pages) and bool(pages[page - 1]))
        require(
            hashlib.sha256(pages[page - 1].encode("utf-8")).hexdigest() == selector["quote_sha256"]
        )

    def status(self, evidence):
        try:
            return self.resolve(evidence)
        except KnowledgeObjectError as exc:
            return {
                "id": evidence.get("id") if type(evidence) is dict else None,
                "status": "UNAVAILABLE",
                "reason": exc.code,
                "truth": "NOT_VERIFIED",
            }

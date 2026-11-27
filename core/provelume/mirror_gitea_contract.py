"""Closed Gitea 28.3.0 API-v1 current-token profile; no inherited host proof."""

import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from .mirror_contract import MirrorError, raw, require, sha
from .mirror_git_target import target_configuration

VERSION = "28.3.0"
PROFILE = "gitea/28.3.0/v1/current-token"
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def endpoint(value):
    require(type(value) is str and 0 < len(value) <= 512, "gitea_endpoint")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise MirrorError("gitea_endpoint") from None
    require(
        parsed.scheme == "https"
        and parsed.netloc
        and not parsed.path
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.hostname
        and all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", label)
            for label in parsed.hostname.split(".")
        )
        and (port is None or 1 <= port <= 65535),
        "gitea_endpoint",
    )
    return parsed


def validate_ca(ca_pem):
    require(
        type(ca_pem) is str
        and len(ca_pem.encode()) <= 4096
        and (
            not ca_pem or ("-----BEGIN CERTIFICATE-----" in ca_pem and "PRIVATE KEY" not in ca_pem)
        ),
        "gitea_certificate",
    )
    require(ca_pem.isascii(), "gitea_certificate")
    return ca_pem


def tls_context(ca_pem):
    validate_ca(ca_pem)
    try:
        return ssl.create_default_context(cadata=ca_pem or None)
    except (ValueError, ssl.SSLError):
        raise MirrorError("gitea_certificate") from None


def configuration(value):
    require(
        type(value) is dict
        and set(value)
        == {
            "transport",
            "repository",
            "repository_id",
            "visibility",
            "namespace",
            "api_version",
            "server_version",
            "endpoint",
            "ca_pem",
            "branch",
            "path",
            "commit_name",
            "commit_email",
        },
        "gitea_target",
    )
    require(
        value["transport"] == "gitea"
        and value["api_version"] == "v1"
        and value["server_version"] == VERSION,
        "gitea_profile_not_qualified",
    )
    endpoint(value["endpoint"])
    validate_ca(value["ca_pem"])
    repository = value["repository"]
    require(
        type(repository) is str
        and len(repository.split("/")) == 2
        and all(PART.fullmatch(part) for part in repository.split("/"))
        and not repository.endswith(".git"),
        "gitea_target",
    )
    require(type(value["repository_id"]) is int and value["repository_id"] > 0, "gitea_target")
    require(value["visibility"] in {"private", "public"}, "visibility_unknown")
    require(
        type(value["namespace"]) is str and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "gitea_namespace",
    )
    target_configuration(
        {key: value[key] for key in ("branch", "path", "commit_name", "commit_email")}
        | {"transport": "local", "repository": str(Path.cwd().anchor)}
    )
    require(len(raw(value)) <= 4096, "limit")
    return value


def token_observation(value, user, target):
    require(type(value) is dict and type(user) is dict, "gitea_response")
    require(
        type(user.get("id")) is int
        and user["id"] > 0
        and type(user.get("login")) is str
        and PART.fullmatch(user["login"]),
        "gitea_identity",
    )
    principal = value.get("user")
    require(
        type(principal) is dict
        and type(principal.get("id")) is int
        and principal.get("id") == user["id"]
        and principal.get("login") == user["login"],
        "gitea_identity_changed",
    )
    scopes = value.get("scopes")
    require(
        type(scopes) is list
        and 0 < len(scopes) <= 32
        and all(type(scope) is str and 0 < len(scope) <= 80 for scope in scopes)
        and len(set(scopes)) == len(scopes),
        "gitea_token_profile",
    )
    require(
        "all" in scopes
        or ("write:repository" in scopes and bool({"read:user", "write:user"} & set(scopes))),
        "gitea_write_unproven",
    )
    require("public-only" not in scopes or target["visibility"] == "public", "gitea_write_unproven")
    return {"kind": "user", "id": user["id"], "login": user["login"], "scopes": sorted(scopes)}


def repository_observation(value, target):
    configuration(target)
    expected = target["endpoint"] + "/" + target["repository"]
    require(
        type(value) is dict
        and type(value.get("id")) is int
        and value.get("id") == target["repository_id"]
        and value.get("full_name") == target["repository"]
        and value.get("clone_url") == expected + ".git"
        and value.get("html_url") == expected,
        "gitea_repository_changed",
    )
    require(
        type(value.get("private")) is bool and value.get("internal") is False, "visibility_unknown"
    )
    visibility = "private" if value["private"] else "public"
    require(visibility == target["visibility"], "gitea_visibility_changed")
    require(
        value.get("archived") is False
        and type(value.get("permissions")) is dict
        and value["permissions"].get("push") is True,
        "gitea_read_only",
    )
    return {
        "repository_id": value["id"],
        "repository": value["full_name"],
        "clone_url": value["clone_url"],
        "visibility": visibility,
        "api_version": "v1",
        "server_version": VERSION,
        "trust_sha256": sha(target["ca_pem"].encode("ascii")),
        "trust_mode": "EXPLICIT_CA" if target["ca_pem"] else "SYSTEM_ROOTS",
    }


def marker(target):
    return {"schema": "provelume-gitea-namespace/v1", "tag": target["namespace"]}

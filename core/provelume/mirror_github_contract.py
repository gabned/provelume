"""Closed GitHub.com profile. Provider observations never come from a UI checkbox."""

from __future__ import annotations

import hashlib
import re

from .mirror_contract import fingerprint, require
from .mirror_git_target import target_configuration

API_VERSION = "2022-11-28"
PROBE = b"Provelume synthetic Contents-write permission probe v1\n"
PROBE_OID = hashlib.sha1(b"blob " + str(len(PROBE)).encode() + b"\0" + PROBE).hexdigest()
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def configuration(value):
    require(
        type(value) is dict
        and set(value)
        == {
            "transport",
            "repository",
            "branch",
            "path",
            "commit_name",
            "commit_email",
            "repository_id",
            "visibility",
            "namespace",
            "api_version",
        },
        "github_target",
    )
    require(
        value["transport"] == "github" and value["api_version"] == API_VERSION,
        "github_profile_not_qualified",
    )
    repository = value["repository"]
    require(
        type(repository) is str
        and len(repository.split("/")) == 2
        and all(NAME.fullmatch(part) for part in repository.split("/"))
        and not repository.endswith(".git"),
        "github_target",
    )
    require(type(value["repository_id"]) is int and value["repository_id"] > 0, "github_target")
    require(value["visibility"] in {"private", "public"}, "visibility_unknown")
    require(
        type(value["namespace"]) is str and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "github_namespace",
    )
    # The common branch, prefix and explicit identity contract is unchanged.
    from pathlib import Path

    target_configuration(
        {key: value[key] for key in ("branch", "path", "commit_name", "commit_email")}
        | {"transport": "local", "repository": str(Path.cwd().anchor)}
    )
    return value


def repository_observation(value, target):
    configuration(target)
    require(type(value) is dict, "github_response")
    require(
        value.get("id") == target["repository_id"]
        and value.get("full_name") == target["repository"]
        and value.get("clone_url") == "https://github.com/" + target["repository"] + ".git",
        "github_repository_changed",
    )
    visibility = value.get("visibility")
    require(
        visibility in {"private", "public"}
        and type(value.get("private")) is bool
        and value["private"] == (visibility == "private"),
        "visibility_unknown",
    )
    require(visibility == target["visibility"], "github_visibility_changed")
    require(value.get("archived") is False and value.get("disabled") is False, "github_read_only")
    permissions = value.get("permissions")
    require(type(permissions) is dict and permissions.get("push") is True, "github_read_only")
    return {
        "repository_id": value["id"],
        "repository": value["full_name"],
        "visibility": visibility,
        "clone_url": value["clone_url"],
        "api_version": API_VERSION,
    }


def user_identity(value):
    require(
        type(value) is dict
        and type(value.get("id")) is int
        and value["id"] > 0
        and type(value.get("login")) is str
        and NAME.fullmatch(value["login"]),
        "github_identity",
    )
    return {"kind": "user", "id": value["id"], "login": value["login"]}


def marker(target):
    return {"schema": "provelume-github-namespace/v1", "tag": target["namespace"]}


def access_identity(*, mode, repository, principal=None):
    require(mode in {"user", "installation"}, "github_identity")
    # Installation tokens identify a repository access grant, not a human user.
    require(mode != "user" or principal is not None, "github_identity")
    return {
        "mode": mode,
        "principal": principal,
        "repository_id": repository["repository_id"],
        "repository": repository["repository"],
        "grant_sha256": fingerprint([mode, principal, repository["repository_id"]]),
    }

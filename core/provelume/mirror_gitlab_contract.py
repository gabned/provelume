"""Independent GitLab.com v4 classic-PAT capability observations."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

from .mirror_contract import fingerprint, require
from .mirror_git_target import target_configuration

PROFILE = "gitlab.com/v4/classic-pat"
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


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
            "branch",
            "path",
            "commit_name",
            "commit_email",
        },
        "gitlab_target",
    )
    require(
        value["transport"] == "gitlab" and value["api_version"] == "v4",
        "gitlab_profile_not_qualified",
    )
    repository = value["repository"]
    require(
        type(repository) is str
        and len(repository) <= 512
        and 2 <= len(repository.split("/")) <= 6
        and all(PART.fullmatch(part) and part not in {".", ".."} for part in repository.split("/"))
        and not repository.endswith(".git"),
        "gitlab_target",
    )
    require(type(value["repository_id"]) is int and value["repository_id"] > 0, "gitlab_target")
    require(value["visibility"] in {"private", "public"}, "visibility_unknown")
    require(
        type(value["namespace"]) is str and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "gitlab_namespace",
    )
    target_configuration(
        {key: value[key] for key in ("branch", "path", "commit_name", "commit_email")}
        | {"transport": "local", "repository": str(Path.cwd().anchor)}
    )
    return value


def token_observation(value, user, *, today=None):
    require(type(value) is dict and type(user) is dict, "gitlab_response")
    require(
        type(user.get("id")) is int
        and user["id"] > 0
        and type(user.get("username")) is str
        and PART.fullmatch(user["username"])
        and user.get("state") == "active",
        "gitlab_identity",
    )
    require(
        value.get("user_id") == user["id"]
        and value.get("active") is True
        and value.get("revoked") is False,
        "authorization_required",
    )
    scopes = value.get("scopes")
    require(
        type(scopes) is list
        and 0 < len(scopes) <= 32
        and all(type(scope) is str and len(scope) <= 80 for scope in scopes)
        and len(set(scopes)) == len(scopes)
        and not value.get("granular_scopes"),
        "gitlab_token_profile",
    )
    require(
        "api" in scopes or {"read_api", "write_repository"} <= set(scopes), "gitlab_write_unproven"
    )
    expiry = value.get("expires_at")
    if expiry is not None:
        require(
            type(expiry) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry),
            "gitlab_token_profile",
        )
        try:
            future = date.fromisoformat(expiry) > (today or datetime.now(UTC).date())
        except ValueError:
            future = False
        require(future, "authorization_required")
    return {
        "kind": "user",
        "id": user["id"],
        "login": user["username"],
        "git_write_scope": "api" if "api" in scopes else "read_api+write_repository",
    }


def repository_observation(value, target):
    configuration(target)
    require(
        type(value) is dict
        and value.get("id") == target["repository_id"]
        and value.get("path_with_namespace") == target["repository"]
        and value.get("http_url_to_repo") == "https://gitlab.com/" + target["repository"] + ".git"
        and value.get("web_url") == "https://gitlab.com/" + target["repository"],
        "gitlab_repository_changed",
    )
    visibility = value.get("visibility")
    require(visibility in {"private", "public"}, "visibility_unknown")
    require(visibility == target["visibility"], "gitlab_visibility_changed")
    require(
        value.get("archived") is False and value.get("repository_access_level") == "enabled",
        "gitlab_read_only",
    )
    permissions = value.get("permissions")
    require(type(permissions) is dict, "gitlab_write_unproven")
    levels = []
    for name in ("project_access", "group_access"):
        access = permissions.get(name)
        if access is not None:
            require(
                type(access) is dict
                and type(access.get("access_level")) is int
                and access["access_level"] in {0, 5, 10, 15, 20, 25, 30, 40, 50},
                "gitlab_write_unproven",
            )
            levels.append(access["access_level"])
    require(levels and max(levels) >= 30, "gitlab_write_unproven")
    return {
        "repository_id": value["id"],
        "repository": value["path_with_namespace"],
        "visibility": visibility,
        "clone_url": value["http_url_to_repo"],
        "api_version": "v4",
        "effective_access_level": max(levels),
    }


def marker(target):
    return {"schema": "provelume-gitlab-namespace/v1", "tag": target["namespace"]}


def identity_observation(user, token_info, repository):
    principal = token_observation(token_info, user)
    return {
        "mode": "classic-pat",
        "principal": principal,
        "repository_id": repository["repository_id"],
        "repository": repository["repository"],
        "grant_sha256": fingerprint([PROFILE, principal["id"], repository["repository_id"]]),
    }

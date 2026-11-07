"""Shared owned secret-pipe mechanism; provider wrappers close host and grant type."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from .mirror_contract import require
from .mirrors import Mirrors
from .storage import InstanceStore


def configure_session(session, *, store, destination_id, binding, reference, provider):
    require(provider in {"github", "gitlab"})
    command = [sys.executable]
    if getattr(sys, "frozen", False):
        command += ["--internal-" + provider + "-git-credential"]
    else:
        command += ["-m", "provelume.mirror_" + provider + "_helper"]
        session.environment["PYTHONPATH"] = str(Path(__file__).absolute().parent.parent)
        session.environment["PYTHONNOUSERSITE"] = "1"
    command += [str(store.paths.root), destination_id, reference, binding["credential_epoch"]]
    # Git's helper syntax uses its own shell. All arguments are owned values and
    # quoted independently; neither token nor server-supplied text is present.
    helper = "!" + " ".join(shlex.quote(part.replace("\\", "/")) for part in command)
    session.transport_configuration = [
        "-c",
        "credential.useHttpPath=true",
        "-c",
        "credential.helper=" + helper,
        "-c",
        "maintenance.auto=false",
        "-c",
        "receive.autogc=false",
        "-c",
        "fetch.recurseSubmodules=false",
        "-c",
        "submodule.recurse=false",
    ]
    session.environment["GIT_ALLOW_PROTOCOL"] = "https"


def credential_response(payload, *, target, credential, host, configuration):
    require(
        type(payload) is bytes and len(payload) <= 16384,
        host.split(".", 1)[0] + "_credential_query",
    )
    fields = {}
    for line in payload.decode("utf-8").splitlines():
        if not line:
            continue
        key, separator, value = line.partition("=")
        require(
            separator
            and key
            in {"protocol", "host", "path", "username", "capability[]", "wwwauth[]", "state[]"},
            host.split(".", 1)[0] + "_credential_query",
        )
        if key.endswith("[]"):
            continue
        require(key not in fields, host.split(".", 1)[0] + "_credential_query")
        fields[key] = value
    configuration(target)
    require(
        fields.get("protocol") == "https"
        and fields.get("host") == host
        and fields.get("path") == target["repository"] + ".git"
        and fields.get("username", "x-access-token") == "x-access-token",
        host.split(".", 1)[0] + "_credential_query",
    )
    token = credential["token"]
    require(
        type(token) is str
        and 0 < len(token) <= 8192
        and all(32 < ord(char) < 127 for char in token),
        "authorization_required",
    )
    return ("username=x-access-token\npassword=" + token + "\n\n").encode("ascii")


def main(*, provider):
    if provider == "github":
        from .mirror_github_contract import configuration
        from .mirror_github_credentials import GitHubCredentials as Credentials

        host = "github.com"
    elif provider == "gitlab":
        from .mirror_gitlab_contract import configuration
        from .mirror_gitlab_credentials import GitLabCredentials as Credentials

        host = "gitlab.com"
    else:
        return 2
    try:
        args = sys.argv[1:]
        if args[:1] == ["--internal-" + provider + "-git-credential"]:
            args = args[1:]
        require(len(args) == 5)
        root, destination_id, reference, epoch, action = args
        require(action in {"get", "store", "erase"})
        if action != "get":
            return 0
        mirrors = Mirrors(InstanceStore(Path(root)))
        access = mirrors.access()
        require(access["enabled"] and (provider != "github" or access["github"]), "github_disabled")
        row = mirrors.destination(destination_id)
        identity = mirrors.identity(row["identity_id"])
        require(identity["profile"] == provider, provider + "_profile_not_qualified")
        operations = mirrors.operation_ledger(destination_id, epoch=identity["epoch"])
        pending = operations["inflight"]
        mirrors.authority(
            destination_id,
            _inspection_operation=(None if pending is None else pending["operation_id"]),
        )
        grant = mirrors._grant(identity)
        require(grant["credential"] == {"reference": reference}, "authorization_required")
        target = grant["destinations"][destination_id]["target"]
        credential = Credentials(mirrors).read(reference)
        require(credential["epoch"] == epoch, provider + "_credential_changed")
        response = credential_response(
            sys.stdin.buffer.read(16385),
            target=target,
            credential=credential,
            host=host,
            configuration=configuration,
        )
        sys.stdout.buffer.write(response)
        return 0
    except Exception:
        # No exception, server value, credential or private locator in diagnostics.
        return 2

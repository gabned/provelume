"""Exact configured Gitea HTTPS origin/CA and owned Git credential pipe."""

from .mirror_gitea_contract import configuration, endpoint
from .mirror_hosted_helper import configure_session as _configure
from .mirror_hosted_helper import credential_response as _response
from .mirror_hosted_helper import main as _main


def configure_session(session, *, store, destination_id, binding, reference):
    return _configure(
        session,
        store=store,
        destination_id=destination_id,
        binding=binding,
        reference=reference,
        provider="gitea",
    )


def credential_response(payload, *, target, credential):
    return _response(
        payload,
        target=target,
        credential=credential,
        host=endpoint(target["endpoint"]).netloc,
        configuration=configuration,
        provider="gitea",
        username=credential["identity"]["principal"]["login"],
    )


def main():
    return _main(provider="gitea")


if __name__ == "__main__":
    raise SystemExit(main())

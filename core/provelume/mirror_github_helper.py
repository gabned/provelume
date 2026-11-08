"""Fixed github host/target contract over the owned Git credential pipe."""

from .mirror_github_contract import configuration
from .mirror_hosted_helper import (
    configure_session as _configure,
)
from .mirror_hosted_helper import (
    credential_response as _response,
)
from .mirror_hosted_helper import (
    main as _main,
)


def configure_session(session, *, store, destination_id, binding, reference):
    return _configure(
        session,
        store=store,
        destination_id=destination_id,
        binding=binding,
        reference=reference,
        provider="github",
    )


def credential_response(payload, *, target, credential):
    return _response(
        payload,
        target=target,
        credential=credential,
        host="github.com",
        configuration=configuration,
    )


def main():
    return _main(provider="github")


if __name__ == "__main__":
    raise SystemExit(main())

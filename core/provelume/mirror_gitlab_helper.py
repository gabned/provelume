"""Fixed gitlab host/target contract over the owned Git credential pipe."""

from .mirror_gitlab_contract import configuration
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
        provider="gitlab",
    )


def credential_response(payload, *, target, credential):
    return _response(
        payload,
        target=target,
        credential=credential,
        host="gitlab.com",
        configuration=configuration,
    )


def main():
    return _main(provider="gitlab")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .connector_model import (
    CONNECTOR_AUTHORIZATION_MODES,
    CONNECTOR_NETWORK_MODES,
    CONNECTOR_SECRET_REFERENCE_KINDS,
    CONNECTOR_SOURCE_KINDS,
    ConnectorError,
    ConnectorNotFoundError,
)
from .service import ProvelumeInstance


def add_connector_commands(subparsers: Any) -> None:
    inventory = subparsers.add_parser(
        "connector-inventory",
        help="Inspect local connector declarations without making a network request",
    )
    inventory.add_argument("instance", type=Path)

    register = subparsers.add_parser(
        "connector-definition-register",
        help="Validate and register one local connector capability manifest",
    )
    register.add_argument("instance", type=Path)
    register.add_argument("manifest", type=Path)

    create = subparsers.add_parser(
        "connector-instance-create",
        help="Create one isolated connector configuration without accessing its endpoint",
    )
    create.add_argument("instance", type=Path)
    create.add_argument("definition_id")
    create.add_argument("--name", required=True)
    create.add_argument("--provider-identity", required=True)
    create.add_argument("--account-identity")
    create.add_argument(
        "--network-mode",
        choices=CONNECTOR_NETWORK_MODES,
        default="disabled",
    )
    create.add_argument(
        "--origin",
        action="append",
        default=[],
        dest="allowed_origins",
        help="allowed HTTP(S) origin; repeat for multiple origins",
    )
    create.add_argument(
        "--authorization-mode",
        choices=CONNECTOR_AUTHORIZATION_MODES,
        default="none",
    )
    create.add_argument(
        "--scope",
        action="append",
        default=[],
        dest="scopes",
        help="least-privilege scope identifier; repeat for multiple scopes",
    )
    create.add_argument(
        "--secret-ref-kind",
        choices=CONNECTOR_SECRET_REFERENCE_KINDS,
    )
    create.add_argument("--secret-ref-name")

    source = subparsers.add_parser(
        "connector-source-add",
        help="Add one independently identified Source to a connector instance",
    )
    source.add_argument("instance", type=Path)
    source.add_argument("connector_instance_id")
    source.add_argument("--name", required=True)
    source.add_argument("--source-kind", choices=CONNECTOR_SOURCE_KINDS, required=True)
    source.add_argument("--external-id", required=True)


def _manifest(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise ConnectorError("connector definition manifest must be a JSON object")
    return value


def handle_connector_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "connector-inventory",
        "connector-definition-register",
        "connector-instance-create",
        "connector-source-add",
    }:
        return None

    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "connector-inventory":
            result: Any = instance.connector_inventory()
        elif args.command == "connector-definition-register":
            result = instance.register_connector_definition(_manifest(args.manifest))
        elif args.command == "connector-instance-create":
            if bool(args.secret_ref_kind) != bool(args.secret_ref_name):
                raise ConnectorError("secret reference kind and name must be provided together")
            credential_reference = (
                {
                    "kind": args.secret_ref_kind,
                    "name": args.secret_ref_name,
                }
                if args.secret_ref_kind
                else None
            )
            result = instance.create_connector_instance(
                args.definition_id,
                name=args.name,
                provider_identity=args.provider_identity,
                account_identity=args.account_identity,
                network_mode=args.network_mode,
                allowed_origins=args.allowed_origins,
                authorization_mode=args.authorization_mode,
                scopes=args.scopes,
                credential_reference=credential_reference,
            )
        else:
            result = instance.add_connector_source(
                args.connector_instance_id,
                name=args.name,
                source_kind=args.source_kind,
                external_id=args.external_id,
            )
    except (OSError, UnicodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": ("not_found" if isinstance(exc, ConnectorNotFoundError) else "error"),
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                    "network_attempted": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3 if isinstance(exc, ConnectorNotFoundError) else 2

    if isinstance(result, dict):
        result = {**result, "network_attempted": False}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

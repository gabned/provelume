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

_INSTANCE_STATE_COMMANDS = {
    "connector-instance-enable": "enable",
    "connector-instance-disable": "disable",
    "connector-instance-remove": "remove",
}
_SOURCE_STATE_COMMANDS = {
    "connector-source-enable": "enable",
    "connector-source-disable": "disable",
    "connector-source-remove": "remove",
}


def _add_secret_arguments(parser: argparse.ArgumentParser, *, clear: bool = False) -> None:
    parser.add_argument(
        "--secret-ref-kind",
        choices=CONNECTOR_SECRET_REFERENCE_KINDS,
    )
    parser.add_argument("--secret-ref-name")
    if clear:
        parser.add_argument("--clear-credential-reference", action="store_true")


def _add_instance_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("instance", type=Path)
    parser.add_argument("connector_instance_id")


def _add_source_identity(parser: argparse.ArgumentParser) -> None:
    _add_instance_identity(parser)
    parser.add_argument("source_id")


def add_connector_commands(subparsers: Any) -> None:
    inventory = subparsers.add_parser(
        "connector-inventory",
        help="Inspect isolated local connector lifecycle and health declarations",
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
    create.add_argument("--endpoint")
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
    _add_secret_arguments(create)

    show = subparsers.add_parser(
        "connector-instance-show",
        help="Inspect one connector instance without making a network request",
    )
    _add_instance_identity(show)

    update = subparsers.add_parser(
        "connector-instance-update",
        help="Update one isolated connector configuration",
    )
    _add_instance_identity(update)
    update.add_argument("--name")
    update.add_argument("--provider-identity")
    account = update.add_mutually_exclusive_group()
    account.add_argument("--account-identity")
    account.add_argument("--clear-account-identity", action="store_true")
    endpoint = update.add_mutually_exclusive_group()
    endpoint.add_argument("--endpoint")
    endpoint.add_argument("--clear-endpoint", action="store_true")
    update.add_argument("--network-mode", choices=CONNECTOR_NETWORK_MODES)
    origins = update.add_mutually_exclusive_group()
    origins.add_argument("--origin", action="append", dest="allowed_origins")
    origins.add_argument("--clear-origins", action="store_true")
    update.add_argument(
        "--authorization-mode",
        choices=CONNECTOR_AUTHORIZATION_MODES,
    )
    scopes = update.add_mutually_exclusive_group()
    scopes.add_argument("--scope", action="append", dest="scopes")
    scopes.add_argument("--clear-scopes", action="store_true")
    _add_secret_arguments(update, clear=True)

    for command, action in _INSTANCE_STATE_COMMANDS.items():
        parser = subparsers.add_parser(
            command,
            help=f"{action.capitalize()} one connector instance configuration",
        )
        _add_instance_identity(parser)

    source = subparsers.add_parser(
        "connector-source-add",
        help="Add one independently identified Source to a connector instance",
    )
    _add_instance_identity(source)
    source.add_argument("--name", required=True)
    source.add_argument("--source-kind", choices=CONNECTOR_SOURCE_KINDS, required=True)
    source.add_argument("--external-id", required=True)

    source_show = subparsers.add_parser(
        "connector-source-show",
        help="Inspect one independently selected connector Source",
    )
    _add_source_identity(source_show)

    source_update = subparsers.add_parser(
        "connector-source-update",
        help="Update one selected connector Source without changing its identity",
    )
    _add_source_identity(source_update)
    source_update.add_argument("--name", required=True)

    for command, action in _SOURCE_STATE_COMMANDS.items():
        parser = subparsers.add_parser(
            command,
            help=f"{action.capitalize()} one connector Source configuration",
        )
        _add_source_identity(parser)


def _manifest(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise ConnectorError("connector definition manifest must be a JSON object")
    return value


def _credential_reference(args: argparse.Namespace) -> dict[str, str] | None:
    if bool(args.secret_ref_kind) != bool(args.secret_ref_name):
        raise ConnectorError("secret reference kind and name must be provided together")
    if args.secret_ref_kind:
        return {
            "kind": str(args.secret_ref_kind),
            "name": str(args.secret_ref_name),
        }
    return None


def _instance_updates(args: argparse.Namespace) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for field in (
        "name",
        "provider_identity",
        "network_mode",
        "authorization_mode",
    ):
        selected = getattr(args, field)
        if selected is not None:
            updates[field] = selected
    if args.clear_account_identity:
        updates["account_identity"] = None
    elif args.account_identity is not None:
        updates["account_identity"] = args.account_identity
    if args.clear_endpoint:
        updates["endpoint"] = None
    elif args.endpoint is not None:
        updates["endpoint"] = args.endpoint
    if args.clear_origins:
        updates["allowed_origins"] = []
    elif args.allowed_origins is not None:
        updates["allowed_origins"] = args.allowed_origins
    if args.clear_scopes:
        updates["scopes"] = []
    elif args.scopes is not None:
        updates["scopes"] = args.scopes
    has_secret = bool(args.secret_ref_kind) or bool(args.secret_ref_name)
    if args.clear_credential_reference and has_secret:
        raise ConnectorError(
            "credential reference cannot be set and cleared in the same update"
        )
    if args.clear_credential_reference:
        updates["credential_reference"] = None
    elif has_secret:
        updates["credential_reference"] = _credential_reference(args)
    return updates


def _connector_result(
    instance: ProvelumeInstance,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if args.command == "connector-inventory":
        return instance.connector_inventory()
    if args.command == "connector-definition-register":
        return instance.register_connector_definition(_manifest(args.manifest))
    if args.command == "connector-instance-create":
        return instance.create_connector_instance(
            args.definition_id,
            name=args.name,
            provider_identity=args.provider_identity,
            account_identity=args.account_identity,
            endpoint=args.endpoint,
            network_mode=args.network_mode,
            allowed_origins=args.allowed_origins,
            authorization_mode=args.authorization_mode,
            scopes=args.scopes,
            credential_reference=_credential_reference(args),
        )
    if args.command == "connector-instance-show":
        result = instance.get_connector_instance(args.connector_instance_id)
        if result is None:
            raise ConnectorNotFoundError(
                f"connector instance not found: {args.connector_instance_id}"
            )
        return result
    if args.command == "connector-instance-update":
        return instance.update_connector_instance(
            args.connector_instance_id,
            **_instance_updates(args),
        )
    if args.command in _INSTANCE_STATE_COMMANDS:
        method = getattr(
            instance,
            f"{_INSTANCE_STATE_COMMANDS[args.command]}_connector_instance",
        )
        return method(args.connector_instance_id)
    if args.command == "connector-source-add":
        return instance.add_connector_source(
            args.connector_instance_id,
            name=args.name,
            source_kind=args.source_kind,
            external_id=args.external_id,
        )
    if args.command == "connector-source-show":
        result = instance.get_connector_source(
            args.connector_instance_id,
            args.source_id,
        )
        if result is None:
            raise ConnectorNotFoundError(
                f"connector Source not found: {args.source_id}"
            )
        return result
    if args.command == "connector-source-update":
        return instance.update_connector_source(
            args.connector_instance_id,
            args.source_id,
            name=args.name,
        )
    if args.command in _SOURCE_STATE_COMMANDS:
        method = getattr(
            instance,
            f"{_SOURCE_STATE_COMMANDS[args.command]}_connector_source",
        )
        return method(args.connector_instance_id, args.source_id)
    raise ConnectorError(f"unsupported connector command: {args.command}")


def handle_connector_command(args: argparse.Namespace) -> int | None:
    commands = {
        "connector-inventory",
        "connector-definition-register",
        "connector-instance-create",
        "connector-instance-show",
        "connector-instance-update",
        "connector-source-add",
        "connector-source-show",
        "connector-source-update",
        *_INSTANCE_STATE_COMMANDS,
        *_SOURCE_STATE_COMMANDS,
    }
    if args.command not in commands:
        return None

    try:
        result = _connector_result(ProvelumeInstance(args.instance), args)
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": (
                        "not_found"
                        if isinstance(exc, ConnectorNotFoundError)
                        else "error"
                    ),
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                    "network_attempted": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3 if isinstance(exc, ConnectorNotFoundError) else 2

    print(
        json.dumps(
            {**result, "network_attempted": False},
            indent=2,
            sort_keys=True,
        )
    )
    return 0

"""Closed acquisition provenance for inert email bundles; reading never fetches remotely."""

import hashlib
import json

from .email_contract import EMAIL_ADAPTER_ID, EmailContractError


def acquisition_profile(adapter_id):
    if adapter_id not in {EMAIL_ADAPTER_ID, "provelume.google"}:
        raise EmailContractError("email_derived_invalid", "unsupported email acquisition profile")
    remote = adapter_id == "provelume.google"
    return {"network_access": "explicit_only" if remote else "none",
            "network_used": remote, "remote_fetch": remote}


def provider_observation(store, message, observation):
    if observation["adapter_id"] != "provelume.google":
        return None
    fields = ("provider_item_ref_sha256", "provider_revision_ref_sha256",
              "provider_thread_ref_sha256", "provider_label_ref_sha256",
              "provider_observed_at", "authoritative", "source_scoped")
    matches = {}
    for row in store.list_canonical("google-gmail-observations"):
        if (row.get("message_id") == message["id"]
                and row.get("source_id") == message["source_id"]
                and row.get("provider_item_ref_sha256") == observation["locator_sha256"]
                and hashlib.sha256(
                    f"google-gmail-revision:{row.get('provider_revision_ref_sha256')}".encode()
                ).hexdigest() == observation["container_snapshot_sha256"]):
            value = {key: row[key] for key in fields}
            matches[json.dumps(value, sort_keys=True)] = value
    if len(matches) != 1:
        raise EmailContractError("email_derived_invalid", "Gmail acquisition evidence is ambiguous")
    return next(iter(matches.values()))


def manifest_acquisition_matches(store, manifest, message):
    binding = manifest.get("message", {})
    if not isinstance(binding, dict):
        return False
    observation = store.read_canonical("email-observations", str(binding.get("observation_id")))
    if (observation is None or observation.get("message_id") != message["id"]
            or observation.get("source_id") != message["source_id"]
            or observation.get("adapter_id") != message["adapter_id"]
            or observation.get("adapter_version") != message["adapter_version"]):
        return False
    try:
        profile = acquisition_profile(observation["adapter_id"])
        return (manifest.get("adapter") == {
                    "adapter_id": observation["adapter_id"],
                    "adapter_version": observation["adapter_version"],
                    "network_access": profile["network_access"]}
                and manifest.get("network_used") is profile["network_used"]
                and manifest.get("remote_fetch") is profile["remote_fetch"]
                and manifest.get("provider_observation") ==
                    provider_observation(store, message, observation))
    except (EmailContractError, KeyError, TypeError):
        return False

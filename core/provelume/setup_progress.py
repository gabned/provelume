"""Private device progress, not portable preferences or operation authority (K)."""

import json
import os
import re
from copy import deepcopy
from pathlib import Path

from .shell_settings import ShellSettingsManager, default_settings
from .storage import InstanceStore

STEPS = ("space", "folders", "ocr", "automation", "test", "summary")
FIELDS = {"schema_version", "instance_id", "revision", "step", "completed",
          "configuration_revisions", "operations"}


class SetupProgressError(ValueError):
    pass


def _validate(value, instance_id):
    if (not isinstance(value, dict) or set(value) != FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["instance_id"] != instance_id or type(value["revision"]) is not int
            or not 0 <= value["revision"] <= 10000 or not isinstance(value["step"], str)
            or value["step"] not in STEPS
            or not isinstance(value["completed"], list)
            or any(not isinstance(item, str) for item in value["completed"])
            or len(value["completed"]) != len(set(value["completed"]))
            or not set(value["completed"]) <= set(STEPS)
            or not isinstance(value["configuration_revisions"], dict)
            or not set(value["configuration_revisions"]) <= set(STEPS)
            or any(re.fullmatch(r"[0-9a-f]{64}", str(v)) is None
                   for v in value["configuration_revisions"].values())
            or not isinstance(value["operations"], dict)
            or not set(value["operations"]) <= {"prepare", "ocr_install", "test", "apply"}
            or any(re.fullmatch(r"op_[0-9a-f]{32}", str(v)) is None
                   for v in value["operations"].values())):
        raise SetupProgressError("setup_progress_invalid")
    return value


class SetupProgress:
    def __init__(self, settings_path, instance_id):
        if re.fullmatch(r"inst_[0-9a-f]{32}", instance_id) is None:
            raise SetupProgressError("setup_instance_invalid")
        self.instance_id = instance_id
        self.root = Path(settings_path).parent / "setup-progress"
        self.path = self.root / (instance_id + ".json")

    def _guard(self):
        for path in (self.root, *self.root.parents, self.path):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise SetupProgressError("setup_progress_invalid")

    def read(self):
        self._guard()
        if not self.path.exists():
            return {"schema_version": 1, "instance_id": self.instance_id, "revision": 0,
                    "step": STEPS[0], "completed": [], "configuration_revisions": {},
                    "operations": {}}
        with self.path.open("rb") as handle:
            raw = handle.read(8193)
        if len(raw) > 8192:
            raise SetupProgressError("setup_progress_invalid")
        try:
            def unique(pairs):
                result = {}
                for key, item in pairs:
                    if key in result:
                        raise SetupProgressError("setup_progress_invalid")
                    result[key] = item
                return result
            return _validate(json.loads(raw, object_pairs_hook=unique), self.instance_id)
        except (ValueError, TypeError, KeyError) as exc:
            raise SetupProgressError("setup_progress_invalid") from exc

    def update(self, *, expected_revision, step, completed=None, bindings=None, operations=None):
        if type(expected_revision) is not int:
            raise SetupProgressError("setup_progress_stale")
        self._guard()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with ShellSettingsManager(self.root / "progress-lock.json", default_settings()).hold():
            current = self.read()
            if current["revision"] != expected_revision or expected_revision >= 10000:
                raise SetupProgressError("setup_progress_stale")
            value = {**deepcopy(current), "revision": current["revision"] + 1, "step": step}
            if completed is not None:
                value["completed"] = list(completed)
            if bindings is not None:
                value["configuration_revisions"] = dict(bindings)
            if operations is not None:
                value["operations"] = dict(operations)
            _validate(value, self.instance_id)
            InstanceStore._atomic_text(self.path, json.dumps(value, sort_keys=True) + "\n")
            if os.name != "nt":
                self.path.chmod(0o600)
            return value

    def discard(self, *, expected_revision):
        # Keep the monotonic revision and references to real applied effects.
        # Discarding navigation must not make a stale second tab current again.
        return self.update(expected_revision=expected_revision, step=STEPS[0],
                           completed=[], bindings={})

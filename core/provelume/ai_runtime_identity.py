"""Native artifact identity, readable by an offline build without runtime dependencies."""

import hashlib
import json
from importlib.resources import files

LOCK_SHA256 = "0e508965cddc60d6cfb57c42d2c4039c637e8812bb25cc21b525b6d6047a4404"


def read_runtime_lock():
    raw = files("provelume").joinpath("ai_runtime_lock.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != LOCK_SHA256:
        raise ValueError("untrusted native artifact lock")
    return json.loads(raw)

"""Bounded requests through the running application's actual HTTP route stack.

Only exact synthetic Document/Original paths are selected. No supplied URL,
redirect, external transport, client click or claimed response is accepted.
"""

import asyncio

from .review_effects import ReviewError, ReviewUnavailable
from .setup_trials import SetupTrials


async def _get(app, path, *, host, port, maximum, query_string=b""):
    completed = asyncio.Event()
    requested = False
    status, body = None, bytearray()

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await completed.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            if status is not None:
                raise ReviewUnavailable("The trial resource returned an invalid response")
            status = message["status"]
        elif message["type"] == "http.response.body":
            data = message.get("body", b"")
            if len(body) + len(data) > maximum:
                raise ReviewUnavailable("The trial resource exceeded its response bound")
            body.extend(data)
            if not message.get("more_body", False):
                completed.set()

    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "scheme": "http", "method": "GET", "path": path,
             "raw_path": path.encode("ascii"), "query_string": query_string, "root_path": "",
             "headers": [(b"host", authority.encode("ascii"))],
             "client": ("127.0.0.1", 0), "server": (host, port)}
    async with asyncio.timeout(10):
        await app(scope, receive, send)
    if status is None or not completed.is_set():
        raise ReviewUnavailable("The trial resource response is incomplete")
    return status, bytes(body)


async def verify_trial_http(app, store, op_id, *, host="127.0.0.1", port=8765):
    trials = SetupTrials(store)
    observation = trials.observations(op_id)
    if not observation["processing_ready"]:
        raise ReviewUnavailable("Complete acquisition, text, search and Inbox before consultation")
    responses = {}
    for row in observation["documents"]:
        acquisition = row["acquisition"]
        try:
            document = await _get(app, f"/documents/{acquisition['document_id']}",
                                  host=host, port=port, maximum=512 * 1024)
        except Exception:
            # A failed application response is evidence of failure. Preserve no
            # private traceback/body as a success or user-facing diagnostic.
            document = 0, b""
        expected = next(item["input"]["size_bytes"] for item in observation["permit"][
            "selection"]["inputs"] if item["input"]["locator"] == acquisition["locator"])
        try:
            original = await _get(app, f"/api/v1/documents/{acquisition['document_id']}/original",
                                  host=host, port=port, maximum=expected + 1)
        except Exception:
            original = 0, b""
        responses[acquisition["id"]] = document, original
    return await asyncio.to_thread(trials.record_consultation, op_id, responses)


async def verify_trial_recovery(app, store, op_id):
    """Qualify a controlled HTTP failure before Apply expires the trial permit."""
    trials = SetupTrials(store)
    count = len(trials.probe_history(op_id))

    async def unavailable(scope, receive, send):
        if scope["path"].startswith("/documents/"):
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b"Synthetic unavailable"})
        else:
            await app(scope, receive, send)

    try:
        await verify_trial_http(unavailable, store, op_id)
    except ReviewError:
        pass
    else:
        raise ReviewUnavailable("Failed consultation was incorrectly accepted")
    history = trials.probe_history(op_id)
    if len(history) != count + 1 or history[-1]["record"]["success"]:
        raise ReviewUnavailable("The actual failed HTTP observation was not retained")
    if trials.observations(op_id)["complete"]:
        raise ReviewUnavailable("Failed consultation retained a complete result")
    if not (await verify_trial_http(app, store, op_id))["complete"]:
        raise ReviewUnavailable("Consultation recovery did not complete")
    return [row["record"]["success"] for row in trials.probe_history(op_id)]

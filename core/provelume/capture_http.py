"""Local owner Capture and a separate, explicitly configured HTTPS-only device app."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_escape
import json
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .atomic_commit import AtomicCommitError
from .capture_adapter import CaptureAdapter
from .capture_authority import SCOPE, CaptureAuthority, trusted_capture_origin
from .capture_journal import CaptureJournal, CaptureJournalError, _read, _unique
from .capture_payloads import capture_capabilities
from .capture_quarantine import CaptureQuarantine
from .capture_requests import CaptureRequestError
from .catalog_registry import SUPPORTED_LANGUAGES, message, namespace_catalog, raw_catalog, registry
from .instance_lifecycle import InstanceLifecycleError
from .review_security import ReviewBrowserSessions, require_local_browser
from .storage import InstanceStore
from .web_security import CONTENT_SECURITY_POLICY, SECURITY_HEADERS

PACKAGE = Path(__file__).resolve().parent
PUBLIC_FILES = {
    "/capture/shell.js": ("capture-shell.js", "text/javascript"),
    "/capture/style.css": ("capture.css", "text/css"),
    "/capture/worker.js": ("capture-worker.js", "text/javascript"),
    "/capture/manifest.webmanifest": ("capture.webmanifest", "application/manifest+json"),
    "/capture/icon.svg": ("capture-icon.svg", "image/svg+xml"),
    "/capture/icon192.png": ("capture-icon192.png", "image/png"),
    "/capture/icon512.png": ("capture-icon512.png", "image/png"),
}
MAX_BODY = 36 * 1024 * 1024


class CaptureAttempts:
    def __init__(self):
        self.lock = Lock()
        self.rows = OrderedDict()

    def check(self, request):
        client = request.client.host if request.client else "missing"
        with self.lock:
            now = monotonic()
            for key, row in list(self.rows.items()):
                if now - row[0] >= 60:
                    del self.rows[key]
            if client not in self.rows:
                if len(self.rows) >= 64:
                    raise HTTPException(429, "Capture authentication capacity reached")
                self.rows[client] = [now, 0]
            self.rows[client][1] += 1
            if self.rows[client][1] > 60:
                raise HTTPException(429, "Capture attempt limit; retry later")


async def capture_json(request, fields, *, maximum=16 * 1024):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "Capture requires JSON")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > maximum:
            raise HTTPException(413, "Capture request exceeds its byte limit")
        raw.extend(chunk)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda v: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HTTPException(400, "Invalid Capture JSON fields") from exc
    return value


def capture_script_bytes():
    words = {code: namespace_catalog(code, "capture") for code in sorted(SUPPORTED_LANGUAGES)}
    for code, values in words.items():
        values["catalogIncomplete"] = any(not value for value in raw_catalog(code).values())
    script = (PACKAGE / "static/capture-shell.js").read_text(encoding="utf-8")
    return script.replace("__CAPTURE_WORDS__", json.dumps(words, ensure_ascii=True)).encode()


def capture_script_integrity():
    digest = hashlib.sha256(capture_script_bytes()).digest()
    return "sha256-" + base64.b64encode(digest).decode()


def capture_worker_bytes():
    words = {code: message(code, "capture.shareUnavailable")
             for code in sorted(SUPPORTED_LANGUAGES)}
    source = (PACKAGE / "static/capture-worker.js").read_text(encoding="utf-8")
    return source.replace("__CAPTURE_SHARE_WORDS__", json.dumps(words, ensure_ascii=True)).replace(
        "__CAPTURE_SHELL_REVISION__", capture_public_revision()).encode()


def capture_public_revision():
    digest = hashlib.sha256((PACKAGE / "templates/capture.html").read_bytes())
    for url, (filename, _) in sorted(PUBLIC_FILES.items()):
        if url != "/capture/worker.js":
            digest.update(filename.encode())
            digest.update((PACKAGE / "static" / filename).read_bytes())
    for path in sorted((PACKAGE / "i18n").glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _capture_headers(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        CONTENT_SECURITY_POLICY.replace("script-src 'none'", "script-src 'self'")
        .replace("worker-src 'none'", "worker-src 'self'")
        .replace("img-src 'self' data:", "img-src 'self' data: blob:")
        .replace("media-src 'self'", "media-src 'self' blob:")
    )
    response.headers["Permissions-Policy"] = (
        SECURITY_HEADERS["Permissions-Policy"]
        .replace("camera=()", "camera=(self)")
        .replace("microphone=()", "microphone=(self)")
    )
    if response.headers.get("Content-Disposition", "").startswith("attachment;"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


def attach_capture_routes(app, store, *, paired_origin=None):
    authority = CaptureAuthority(store)
    sessions = ReviewBrowserSessions(seconds=600, maximum=64)
    attempts = CaptureAttempts()
    ingress = BoundedSemaphore(2)
    instance_id = store.read_config()["instance"]["id"]
    local_device = "dev_" + uuid5(NAMESPACE_URL, f"{instance_id}:local-browser-capture").hex
    subject = f"capture:{instance_id}"
    paired = paired_origin is not None
    app.state.capture_sessions = sessions
    app.state.capture_authority = authority

    def boundary(request, *, mutation=False):
        if request.query_params:
            raise HTTPException(400, "Capture API does not accept query credentials or fields")
        if paired:
            if (
                request.url.scheme != "https"
                or request.headers.get("host", "").lower() != urlsplit(paired_origin).netloc
                or (request.headers.get("origin") and request.headers["origin"] != paired_origin)
                or (mutation and request.headers.get("origin") != paired_origin)
                or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
            ):
                raise HTTPException(403, "Capture HTTPS/origin boundary rejected")
        else:
            require_local_browser(request, mutation=mutation)
            if (
                request.headers.get("origin")
                and request.headers["origin"].rstrip("/") != str(request.base_url).rstrip("/")
            ) or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                raise HTTPException(403, "Capture local origin boundary rejected")

    def owner(request):
        if paired:
            raise HTTPException(404, "Not found")
        boundary(request, mutation=request.method not in {"GET", "HEAD"})
        sessions.check(request.headers.get("x-capture-nonce"), subject)

    from .mobile_retrieval import attach_mobile_retrieval

    attach_mobile_retrieval(app, store, authority, boundary, owner, paired_origin, attempts)

    def access(request, *, mutation=False):
        boundary(request, mutation=mutation)
        if not paired:
            sessions.check(request.headers.get("x-capture-nonce"), subject)
            device, channel = local_device, "local_browser"
        else:
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer "):
                raise HTTPException(403, "Scoped Capture credential required")
            device, channel = request.headers.get("x-capture-device", ""), "paired_pwa"
            authority.authorize(device, header[7:], origin=paired_origin)
        return device, channel

    def adapter(request, *, mutation=False):
        attempts.check(request)
        device, channel = access(request, mutation=mutation)

        def guard(selected, transport, reference):
            current, current_channel = access(request, mutation=mutation)
            if selected != current or transport != current_channel:
                raise PermissionError("Capture credential scope rejected")
            # Paired credentials permit proposals only, never canonical placement.
            # Existing reference existence checks and S05 authority remain mandatory.

        return CaptureAdapter(store, authorize=guard), device, channel

    @app.exception_handler(CaptureJournalError)
    async def capture_error(request, exc):
        code = (
            409
            if any(
                v in str(exc).lower()
                for v in ("conflict", "recovery", "unavailable", "full", "schema", "provenance")
            )
            else 400
        )
        if "capacity admission denied" in str(exc):
            code = 507
        return JSONResponse({"detail": str(exc)}, status_code=code)

    @app.exception_handler(CaptureRequestError)
    async def capture_request_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(PermissionError)
    async def capture_denied(request, exc):
        return JSONResponse(
            {"detail": "Capture permission rejected; reconnect or pair again"}, status_code=403
        )

    @app.exception_handler(AtomicCommitError)
    async def capture_atomic_error(request, exc):
        return JSONResponse(
            {"detail": "Capture commit unavailable; reconcile before retry"}, status_code=409
        )

    @app.exception_handler(InstanceLifecycleError)
    async def capture_busy(request, exc):
        return JSONResponse(
            {"detail": "Instance busy or recovering; reconcile before retry"}, status_code=409
        )

    @app.get("/capture/", response_class=HTMLResponse)
    def page(request: Request):
        if not paired:
            require_local_browser(request)
        request.state.capture_surface = True
        request.state.capture_script_integrity = capture_script_integrity()
        html = (PACKAGE / "templates/capture.html").read_text(encoding="utf-8")
        html = html.replace("__CAPTURE_INTEGRITY__", capture_script_integrity())
        options = '<option value="system" data-i18n="system">' + html_escape.escape(
            message("en", "common.language_system")) + '</option>' + "".join(
            '<option value="' + html_escape.escape(row["id"], quote=True) + '">' +
            html_escape.escape(row["label"]) + '</option>' for row in registry()["languages"]
        )
        html = html.replace("__LANGUAGE_OPTIONS__", options)
        html = html.replace("__CAPTURE_FALLBACK__", html_escape.escape(
            message("en", "common.language_fallback")))
        for key, value in namespace_catalog("en", "capture").items():
            html = html.replace("__CAPTURE_TEXT_" + key + "__", html_escape.escape(value))
        return _capture_headers(HTMLResponse(html))

    def build_resource(filename, media_type):
        def resource(request: Request):
            if not paired:
                require_local_browser(request)
            if (
                filename in {"capture-worker.js", "capture.webmanifest"}
                and request.url.scheme != "https"
            ):
                raise HTTPException(409, "PWA resources disabled for plain-HTTP fallback")
            response = FileResponse(PACKAGE / "static" / filename, media_type=media_type)
            if filename == "capture-shell.js":
                response = Response(capture_script_bytes(), media_type=media_type)
            if filename == "capture-worker.js":
                response = Response(capture_worker_bytes(), media_type=media_type)
                response.headers["Service-Worker-Allowed"] = "/capture/"
            return response

        return resource

    for route, (filename, media_type) in PUBLIC_FILES.items():
        resource = build_resource(filename, media_type)
        app.add_api_route(route, resource, methods=["GET"], include_in_schema=False)

    @app.get("/capture/capabilities")
    def capabilities(request: Request):
        if not paired:
            require_local_browser(request)
        return {
            **capture_capabilities(),
            "transport": "paired_pwa" if paired else "local_browser",
            "credential_retention": "explicit-pairing; browser IndexedDB; forget explicitly",
            "outbox": {"maximum_items": 16, "maximum_bytes": 64 * 1024 * 1024},
            "secure_context_required": True,
            "scope": SCOPE,
        }

    @app.post("/capture/share")
    def share_unavailable():
        # An installed HTTPS worker owns transient OS sharing. No server-side queue.
        raise HTTPException(
            409,
            "Share target unavailable; keep the source item and use file selection "
            "or the already configured watched Drive-drop folder",
        )

    if not paired:

        @app.post("/capture/session")
        async def session(request: Request):
            attempts.check(request)
            boundary(request, mutation=True)
            await capture_json(request, set())
            return dict(
                nonce=sessions.issue(subject),
                device_id=local_device,
                instance_id=instance_id,
                channel="local_browser",
                expires_in=600,
            )

    if paired:

        @app.post("/capture/pair/redeem")
        async def redeem(request: Request):
            attempts.check(request)
            boundary(request, mutation=True)
            value = await capture_json(request, {"challenge", "label", "instance_id"})
            if value["instance_id"] != instance_id:
                raise HTTPException(403, "Capture pairing Instance mismatch")
            return authority.redeem(value["challenge"], value["label"], origin=paired_origin)

    @app.post("/capture/submissions")
    async def submit(request: Request):
        manager, device, channel = adapter(request, mutation=True)
        if not ingress.acquire(blocking=False):
            raise HTTPException(409, "Capture intake busy; no unbounded queued work")
        try:
            value = await capture_json(request, {"metadata", "payload_base64"}, maximum=MAX_BODY)
            try:
                encoded = value["payload_base64"]
                if not isinstance(encoded, str) or len(encoded) > 35 * 1024 * 1024:
                    raise ValueError()
                payload = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, "Invalid Capture byte encoding") from exc
            receipt = await asyncio.to_thread(
                manager.submit, device, payload, value["metadata"], channel=channel
            )
            access(request, mutation=True)
            return {"submission": receipt}
        finally:
            ingress.release()

    @app.get("/capture/submissions")
    def listing(request: Request):
        manager, device, channel = adapter(request)
        rows = manager.journal.list_receipts(device, authorize=lambda d: manager._guard(d, channel))
        access(request)
        return {"submissions": rows}

    @app.get("/capture/submissions/{client}")
    def detail(client: str, request: Request):
        manager, device, channel = adapter(request)
        result = manager.detail(device, client, channel=channel)
        if result is None:
            raise HTTPException(404, "Capture receipt not found")
        access(request)
        return result

    @app.post("/capture/submissions/{client}/process")
    async def process(client: str, request: Request):
        manager, device, channel = adapter(request, mutation=True)
        await capture_json(request, set())
        if not ingress.acquire(blocking=False):
            raise HTTPException(409, "Capture processing busy; reconcile before retry")
        try:
            result = await asyncio.to_thread(manager.process, device, client, channel=channel)
            access(request, mutation=True)
            return result
        finally:
            ingress.release()

    @app.get("/capture/submissions/{client}/original")
    def original(client: str, request: Request):
        manager, device, channel = adapter(request)
        detail = manager.detail(device, client, channel=channel)
        if detail is None or detail["acquisition"] is None:
            raise HTTPException(404, "Acquired Original unavailable")
        digest = detail["acquisition"]["payload_sha256"]
        data = _read(store.paths.root / f"originals/sha256/{digest[:2]}/{digest}", 25 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise CaptureJournalError("Capture Original changed before download")
        manager.journal._read_ready()
        access(request)
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="capture.bin"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    if not paired:

        @app.get("/capture/admin/devices")
        def devices(request: Request):
            owner(request)
            return authority.management()

        @app.post("/capture/admin/origin")
        async def configure(request: Request):
            owner(request)
            value = await capture_json(request, {"origin", "confirm_rebind"})
            return authority.configure(
                value["origin"],
                confirm_rebind=value["confirm_rebind"],
                authorize_owner=lambda: owner(request),
            )

        @app.post("/capture/admin/pair")
        async def pairing(request: Request):
            owner(request)
            await capture_json(request, set())
            value = authority.challenge(authorize_owner=lambda: owner(request))
            import qrcode
            from qrcode.image.svg import SvgPathImage

            image = qrcode.make(
                json.dumps(value, separators=(",", ":")), image_factory=SvgPathImage
            )
            output = BytesIO()
            image.save(output)
            return {**value, "qr_svg": output.getvalue().decode()}

        @app.post("/capture/admin/revoke")
        async def revoke(request: Request):
            owner(request)
            value = await capture_json(request, {"device_id"})
            return authority.revoke(value["device_id"], authorize_owner=lambda: owner(request))

        @app.get("/capture/admin/submissions")
        def owner_submissions(request: Request):
            owner(request)
            quarantine = CaptureQuarantine(store).read()
            journal = CaptureJournal(store)
            journal._read_ready()
            rows = []
            for record in journal._inventory().values():
                submitted = record["receipt"]
                manager = CaptureAdapter(store, authorize=lambda *a: owner(request))
                acquired = manager._record(f"state/capture-processing/{submitted['id']}.json")
                if acquired is not None:
                    manager._assure(
                        acquired,
                        submitted,
                        base64.b64decode(record["payload_base64"], validate=True),
                    )
                detail = {"submission": submitted, "acquisition": acquired}
                rows.append({**detail, "quarantine": quarantine["items"].get(submitted["id"])})
            journal._read_ready()
            owner(request)
            return {"items": rows}

        @app.post("/capture/admin/submissions/{scope}/quarantine")
        async def quarantine(scope: str, request: Request):
            owner(request)
            value = await capture_json(request, {"action", "days", "request_id"})
            return CaptureQuarantine(store).transition(
                scope,
                value["action"],
                value["days"],
                value["request_id"],
                authorize_owner=lambda: owner(request),
            )


def create_capture_app(instance_root, *, trusted_origin):
    """Explicit Capture listener with separately granted reads, no owner administration."""
    origin = trusted_capture_origin(trusted_origin)
    store = InstanceStore.open(instance_root)
    authority = CaptureAuthority(store)
    configured = authority.management()
    if configured["origin"] != origin or not configured["active"]:
        raise PermissionError("Configure the explicit Capture origin in local management first")
    app = FastAPI(title="Provelume scoped Capture", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security(request, call_next):
        if (
            request.url.scheme != "https"
            or request.headers.get("host", "").lower() != urlsplit(origin).netloc
            or (request.headers.get("origin") and request.headers["origin"] != origin)
        ):
            response = JSONResponse(
                {"detail": "Capture requires its explicitly configured HTTPS origin"},
                status_code=403,
            )
        else:
            response = await call_next(request)
        return _capture_headers(response)

    attach_capture_routes(app, store, paired_origin=origin)
    return app

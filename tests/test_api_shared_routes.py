from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from provelume.api import attach_api, build_api


def _app(instance, evidence, *, reuse):
    app = FastAPI()
    attach_api(
        app, instance, installation_verification=evidence, _reuse_static_routes=reuse,
    )
    return app


def test_shared_api_keeps_the_complete_public_schema():
    instance = SimpleNamespace()
    direct = _app(instance, {}, reuse=False)
    shared = _app(instance, {}, reuse=True)
    assert shared.openapi() == direct.openapi()
    assert [(r.path, r.name, r.methods) for r in shared.routes] == [
        (r.path, r.name, r.methods) for r in direct.routes
    ]


def test_shared_api_binds_each_request_and_preserves_validation():
    summaries = [{"id": "first"}, {"id": "second"}]
    apps = [
        _app(
            SimpleNamespace(instance_summary=lambda i=i: summaries[i]),
            {"status": name},
            reuse=True,
        )
        for i, name in enumerate(("first", "second"))
    ]
    with (
        TestClient(apps[0], raise_server_exceptions=False) as first,
        TestClient(apps[1], raise_server_exceptions=False) as second,
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        clients = (first, second)

        def observe(i):
            return clients[i % 2].get("/api/v1/instance").json()

        assert list(pool.map(observe, range(20))) == [summaries[i % 2] for i in range(20)]
        summaries[0] = {"id": "fresh-first"}
        assert first.get("/api/v1/instance").json() == summaries[0]
        assert second.get("/api/v1/instance").json() == summaries[1]
        for name, client in zip(("first", "second"), clients, strict=True):
            assert client.get("/api/v1/security/installation").json() == {"status": name}
            assert client.get("/api/v1/search", params={"q": "x", "limit": 0}) \
                .status_code == 422
            assert client.get("/api/v1/search", params={"q": "", "limit": 201}) \
                .status_code == 422
            assert client.get("/api/v1/security/installation", params={
                "release_bundle": "forged", "expected_manifest_sha256": "forged",
            }).status_code == 400
            assert client.post("/api/v1/instance", json={}).status_code == 405
        # A shared route must still validate responses on every request.
        summaries[0] = ["invalid response shape"]
        assert first.get("/api/v1/instance").status_code == 500
        assert second.get("/api/v1/instance").json() == {"id": "second"}


def test_custom_routers_retain_dependencies_prefix_and_response_settings():
    def deny():
        raise HTTPException(status_code=403, detail="synthetic application guard")

    instance = SimpleNamespace(instance_summary=lambda: {"id": "custom"})
    guarded = FastAPI(dependencies=[Depends(deny)])
    attach_api(guarded, instance, installation_verification={})
    with TestClient(guarded) as client:
        assert client.get("/api/v1/instance").status_code == 403

    class CustomResponse(JSONResponse):
        media_type = "application/vnd.provelume-test+json"

    router = APIRouter(prefix="/custom", tags=["custom"], default_response_class=CustomResponse)
    build_api(instance, router=router)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.get("/custom/api/v1/instance")
        assert result.status_code == 200
        assert result.json() == {"id": "custom"}
        assert result.headers["content-type"] == CustomResponse.media_type
    assert app.openapi()["paths"]["/custom/api/v1/instance"]["get"]["tags"] == ["custom"]

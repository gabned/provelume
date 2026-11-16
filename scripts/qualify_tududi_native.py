"""Qualify actual local Tududi read APIs with disposable synthetic fixtures only.

Requires the two pinned Docker inputs and an unlocked native OS vault. Linux only;
no real account, user-supplied destination, public port or write-back qualification.
"""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from provelume.productivity_intake import ProductivityIntake
from provelume.productivity_jobs import ProductivityJobs
from provelume.service import ProvelumeInstance
from provelume.tududi_connection import TududiConnection

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--allow-synthetic-fixtures", action="store_true", required=True)
args = parser.parse_args()
ROOT = args.directory.absolute()
if os.name != "posix" or ROOT.exists() or ROOT.is_symlink():
    raise ValueError("fresh local Linux fixture directory required")
ROOT.mkdir(mode=0o700)
SOURCE = Path(__file__).absolute().parents[1]
HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
TREE = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=SOURCE, text=True).strip()
if subprocess.check_output(["git", "status", "--porcelain"], cwd=SOURCE):
    raise ValueError("clean exact source required")
ORIGINAL_ENVIRONMENT = {key: os.environ.get(key) for key in ("SSL_CERT_FILE", "NO_PROXY")}
OWNER = uuid.uuid4().hex
NETWORK = "pv-td-" + OWNER
PG = NETWORK + "-db"
IMAGE = "chrisvel/tududi@sha256:0787ac438d460d89e669cdae5ab2b205c7a6424c98fba50bf1209623c50cf3ee"
POSTGRES = "postgres@sha256:ac838714b7d794185a866e5a6b479b954e7d8a070568aa0acac6fe07c3070bf5"
ENV = {
    k: v
    for k, v in os.environ.items()
    if k
    not in {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}
}
CREATED = []


def docker(*args, source=None, timeout=30):
    p = subprocess.run(
        ["docker", *args], input=source, capture_output=True, env=ENV, timeout=timeout
    )
    if p.returncode:
        raise RuntimeError(
            "docker operation failed: "
            + args[0]
            + " stderr_sha256="
            + hashlib.sha256(p.stderr).hexdigest()
        )
    return p.stdout


def create(name, *args):
    docker(
        "create",
        "--name",
        name,
        "--label",
        "org.provelume.owner=" + OWNER,
        "--network",
        NETWORK,
        "--read-only",
        "--cap-drop=ALL",
        "--pids-limit=32",
        *args,
    )
    CREATED.append(name)
    docker("start", name)


def wait_for(check):
    limit = time.monotonic() + 30
    while time.monotonic() < limit:
        try:
            if check():
                return
        except (RuntimeError, OSError):
            pass
        time.sleep(0.25)
    raise RuntimeError("server readiness not demonstrated within 30s")


def ip(name):
    return json.loads(docker("inspect", name))[0]["NetworkSettings"]["Networks"][NETWORK][
        "IPAddress"
    ]


opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
cases, handles = [], []

instance = ProvelumeInstance.initialise(ROOT / "Synthetic Space")
config = instance.store.read_config()
config["network"]["external_access"] = True
instance.store.write_config(config)
manager = TududiConnection(instance.store)
jobs = ProductivityJobs(instance.store, tududi=manager)
instance.scheduler._productivity_manager_factory = lambda _store: jobs
try:
    docker("network", "create", "--internal", "--label", "org.provelume.owner=" + OWNER, NETWORK)
    create(
        PG,
        "--user",
        "70:70",
        "--memory=128m",
        "--tmpfs",
        "/var/lib/postgresql/data:rw,uid=70,gid=70,size=128m",
        "--tmpfs",
        "/var/run/postgresql:rw,uid=70,gid=70,size=1m",
        "--tmpfs",
        "/tmp:rw,size=16m",
        "-e",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        POSTGRES,
        "postgres",
        "-c",
        "shared_buffers=16MB",
        "-c",
        "max_connections=16",
        "-c",
        "min_wal_size=32MB",
        "-c",
        "max_wal_size=32MB",
    )
    wait_for(lambda: docker("exec", PG, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"))
    for label in ("first", "second"):
        docker("exec", PG, "createdb", "-h", "127.0.0.1", "-U", "postgres", label)
        envfile = ROOT / (label + ".env")
        envfile.write_text(
            "DATABASE_URL=postgres://postgres@"
            + PG
            + ":5432/"
            + label
            + "\nTUDUDI_SESSION_SECRET="
            + secrets.token_hex(32)
            + "\nUV_THREADPOOL_SIZE=1\nNODE_OPTIONS=--v8-pool-size=1\n"
            "DISABLE_TELEGRAM=true\nDISABLE_SCHEDULER=true\nNODE_ENV=production\nPORT=3002\n"
        )
        envfile.chmod(0o600)
        name = NETWORK + "-" + label
        create(
            name,
            "--user",
            "1001:1001",
            "--memory=256m",
            "--tmpfs",
            "/tmp:rw,uid=1001,gid=1001,size=16m",
            "--tmpfs",
            "/app/uploads:rw,uid=1001,gid=1001,size=16m",
            "--tmpfs",
            "/app/backups:rw,uid=1001,gid=1001,size=16m",
            "--tmpfs",
            "/app/backend/certs:rw,uid=1001,gid=1001,size=1m",
            "--env-file",
            str(envfile),
            "--entrypoint",
            "/bin/sh",
            IMAGE,
            "/app/backend/cmd/start.sh",
        )
        envfile.unlink()
        address = "http://" + ip(name) + ":3002"

        def healthy(address=address):
            with opener.open(address + "/api/health", timeout=1) as response:
                return response.status == 200

        try:
            wait_for(healthy)
        except RuntimeError:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, env=ENV, timeout=5)
            (ROOT / (label + "-startup.log")).write_bytes(logs.stdout + logs.stderr)
            raise
        program = """const {User,Project,Task,sequelize}=require('./models');
const {createApiToken}=require('./modules/users/apiTokenService');
(async()=>{const label=LABEL;
const u=await User.create({email:label+'@example.invalid',name:'Synthetic '+label,
timezone:'Europe/Rome',email_verified:true,password:require('crypto').randomBytes(24).toString('hex')});
const p=await Project.create({name:'Synthetic project '+label,user_id:u.id});
await Task.create({name:'Synthetic task '+label,user_id:u.id,project_id:p.id,
note:'Fixture only',status:0});
const t=await createApiToken({userId:u.id,name:'Local synthetic qualification'});
console.log('PV_RESULT '+JSON.stringify({id:u.id,tokenId:t.tokenRecord.id,
token:t.rawToken,project:p.uid}));
await sequelize.close();})().catch(()=>process.exit(2));""".replace("LABEL", json.dumps(label))
        # Token is captured in memory only; never a command argument, file or archived log.
        out = docker(
            "exec", "-i", "-w", "/app/backend", name, "node", "-", source=program.encode()
        ).decode()
        record = json.loads(next(x[10:] for x in out.splitlines() if x.startswith("PV_RESULT ")))
        import ssl
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        certificate, key = ROOT / (label + ".crt"), ROOT / (label + ".key")
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            capture_output=True,
            check=True,
            timeout=10,
        )
        key.chmod(0o600)
        requests = []

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self, upstream=address, seen=requests):
                seen.append({"method": "GET", "path": self.path})
                req = urllib.request.Request(
                    upstream + self.path,
                    headers={
                        "Authorization": self.headers.get("Authorization", ""),
                        "Accept": "application/json",
                    },
                )
                try:
                    reply = opener.open(req, timeout=5)
                except urllib.error.HTTPError as error:
                    reply = error
                with reply:
                    raw = reply.read(2 * 1024 * 1024 + 1)
                    self.send_response(reply.code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        handles.append((server, thread, key))
        endpoint = "https://127.0.0.1:" + str(server.server_port)
        # Test CA is public. TLS verification remains enabled in the real owned worker.
        os.environ["SSL_CERT_FILE"] = str(certificate.absolute())
        os.environ["NO_PROXY"] = "127.0.0.1"
        identity = manager.connect(
            {"endpoint": endpoint, "token": record["token"], "server_version": "2.1.0"},
            name="Synthetic " + label,
            confirmed=True,
        )["identity_id"]
        manager.catalogue(identity, confirmed=True)
        assert any(
            row["uid"] == record["project"] for row in manager.catalogs[identity]["projects"]
        )
        source = manager.select_source(
            identity,
            name="Synthetic project " + label,
            scope="project",
            remote_id=record["project"],
            confirmed=True,
        )["source_id"]
        for attempt in ("initial", "replay"):
            job = jobs.queue(source, request_key=label + "-" + attempt)["job"]
            result = instance.scheduler.run_one(job_id=job["id"])
            if result is None or result["status"] != "succeeded":
                (ROOT / (label + "-failed-job.json")).write_text(json.dumps(result, indent=2))
                raise RuntimeError("native Tududi intake did not succeed")
        rows = ProductivityIntake(instance.store).records(source)
        assert (
            len(rows) == 1
            and len(instance.store.versions_for_document(rows[0]["document_id"])) == 1
        )
        assert rows[0]["item"]["description"] == "Fixture only"
        # Revoke only this freshly created synthetic grant in its own server.
        revoke = (
            "const {revokeApiToken}=require('./modules/users/apiTokenService');"
            + "const {sequelize}=require('./models');(async()=>{await revokeApiToken("
            + json.dumps(record["tokenId"])
            + ","
            + json.dumps(record["id"])
            + ");await sequelize.close()})().catch(()=>process.exit(2));"
        )
        docker("exec", "-i", "-w", "/app/backend", name, "node", "-", source=revoke.encode())
        from provelume.productivity_http import ProductivityHttpError

        try:
            manager.get(identity, "/profile")
        except ProductivityHttpError as error:
            assert error.status == 401
        else:
            raise RuntimeError("revoked synthetic token remained usable")
        manager.disconnect(identity, expected_revision=1, confirmed=True)
        assert ProductivityIntake(instance.store).records(source) == rows
        for file in (ROOT / "Synthetic Space").rglob("*"):
            if file.is_file():
                assert record["token"].encode() not in file.read_bytes()
        cases.append(
            {
                "endpoint": label,
                "native_worker": "ProductivityHttp",
                "native_vault": type(manager.vault).__name__,
                "project_intake_replay": "PASS",
                "remote_revoke_401": "PASS",
                "local_revoke_retains_data": "PASS",
                "instance_token_scan": "PASS",
                "requests": requests,
                "token_logged": False,
            }
        )
        print("native product Tududi", label, "PASS", flush=True)
    count = sum(len(x["requests"]) for x in cases)
    archive = ROOT / "Synthetic Portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(ROOT / "Restored Space")
    restored.import_portable(archive)
    assert len(restored.store.list_canonical("objects")) == len(
        instance.store.list_canonical("objects")
    )
    assert sum(len(x["requests"]) for x in cases) == count
    (ROOT / "result.json").write_text(
        json.dumps(
            {
                "result": "PASS_DECLARED_NATIVE_READ_SCOPE",
                "cases": cases,
                "source": {"commit": HEAD, "tree": TREE},
                "public_writeback": "DEFERRED_BY_MAINTAINER; NOT_QUALIFIED",
                "full_provider_matrix": "NOT_INFERRED",
                "product_native_http_worker": "PASS",
                "offline_portable": "PASS",
                "image": IMAGE,
                "network": "internal; no published ports",
            },
            indent=2,
        )
        + "\n"
    )
finally:
    for key, value in ORIGINAL_ENVIRONMENT.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    for server, thread, key in handles:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        key.unlink()
    for name in reversed(CREATED):
        state = json.loads(docker("inspect", name))[0]
        if state["Config"]["Labels"].get("org.provelume.owner") == OWNER:
            docker("rm", "--force", "--volumes", name)
    network = json.loads(docker("network", "inspect", NETWORK))[0]
    if network["Labels"].get("org.provelume.owner") == OWNER:
        docker("network", "rm", NETWORK)
    for envfile in ROOT.glob("*.env"):
        envfile.unlink()

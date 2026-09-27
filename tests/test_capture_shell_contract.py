"""Execute the bundled worker and browser identity primitives in the supplied Node runtime.

These checks do not stand in for real browser/PWA observations.
"""

import json
import shutil
import subprocess
from pathlib import Path

from provelume.capture_requests import capture_payload_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def node(script, *args):
    executable = shutil.which("node")
    assert executable, "Node is required for Capture shell conformance"
    result = subprocess.run(
        [executable, "--input-type=module", "-e", script, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_browser_fingerprint_matches_unicode_metadata_and_exact_bytes():
    metadata = {
        "schema_version": 1,
        "client_submission_id": "b5f127f9-1d95-4f6e-8c08-4c0729c775fa",
        "captured_at": "2026-09-27T12:00:00Z",
        "mode": "text",
        "channel": "local_browser",
        "note": "È un testo sintetico: 漢字",
        "filename": "capture.txt",
        "declared_mime": "text/plain",
    }
    payload = "Exact bytes: è 漢字\n".encode()
    script = r"""
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
const source = readFileSync('core/provelume/static/capture-shell.js','utf8')
  .replace(/\}\)\(\);\s*$/, 'globalThis.test={fingerprint,validEntry};})();');
const scope = {navigator:{language:'en'},document:{addEventListener(){}},
  crypto:webcrypto, TextEncoder, Uint8Array,DataView,BigInt};
vm.createContext(scope);vm.runInContext(source,scope);
const metadata=JSON.parse(process.argv[1]);
const bytes=Uint8Array.from(Buffer.from(process.argv[2],'hex'));
console.log(JSON.stringify(await scope.test.fingerprint(bytes,metadata)));
"""
    assert node(script, json.dumps(metadata), payload.hex()) == capture_payload_fingerprint(
        payload, metadata, transport_channel="local_browser"
    )


def test_worker_excludes_authenticated_and_knowledge_requests_and_bounds_public_cache():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const listeners={}, cached=[], fetched=[];
let oversized=false, failNetwork=false;
const scope={URL,Response,self:{location:{origin:'https://capture.test'},clients:{claim:async()=>{}},
  addEventListener:(kind,callback)=>listeners[kind]=callback},
  caches:{open:async()=>({put:async(path,response)=>cached.push(path)}),keys:async()=>[],
    match:async()=>new Response('public fallback')},
  fetch:async(path,options)=>{
    if(failNetwork)throw new Error('offline');
    fetched.push({path,options});return new Response('x'.repeat(oversized?262145:2));}};
vm.createContext(scope);vm.runInContext(readFileSync('core/provelume/static/capture-worker.js','utf8'),scope);
let installation;listeners.install({waitUntil:p=>installation=p});await installation;
assert.equal(cached.length,7);assert(fetched.every(row=>row.options.credentials==='omit'));
for(const request of [
  new Request('https://capture.test/capture/submissions'),
  new Request('https://capture.test/capture/submissions/id/original'),
  new Request('https://capture.test/capture/?credential=value'),
  new Request('https://capture.test/capture/',{headers:{Authorization:'Bearer synthetic'}}),
  new Request('https://capture.test/capture/',{headers:{'X-Capture-Nonce':'synthetic'}}),
  new Request('https://foreign.test/capture/'),
  new Request('https://capture.test/capture/',{method:'POST'})
]){
  let intercepted=false;listeners.fetch({request,respondWith:()=>intercepted=true});
  assert.equal(intercepted,false);
}
failNetwork=true;let fallback;
listeners.fetch({request:new Request('https://capture.test/capture/'),respondWith:p=>fallback=p});
assert.equal(await (await fallback).text(),'public fallback');
failNetwork=false;oversized=true;listeners.install({waitUntil:p=>installation=p});
await assert.rejects(installation,/size bound/);
console.log(JSON.stringify({public_assets:7,private_requests_excluded:7,oversize_rejected:true,offline_public_shell:true}));
"""
    assert node(script)["oversize_rejected"] is True

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


def test_pair_confirmation_requires_explicit_accept_and_escape_fails_closed():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const elements={}; let focus=null;
for(const id of ['pair-confirm','pair','pair-confirm-title','pair-confirm-destination',
  'pair-confirm-accept','pair-confirm-cancel']){
  elements[id]={textContent:'',disabled:false,focus:()=>focus=id};
}
const dialog=elements['pair-confirm'];
dialog.showModal=()=>dialog.open=true;
dialog.close=()=>{dialog.open=false;dialog.onclose?.();};
const scope={navigator:{language:'en'},
  document:{addEventListener(){},getElementById:id=>elements[id]}};
const source=readFileSync('core/provelume/static/capture-shell.js','utf8')
  .replace(/\}\)\(\);\s*$/,'globalThis.test={confirmPairDestination};})();');
vm.createContext(scope);vm.runInContext(source,scope);
const destination={origin:'https://capture.test',instance_id:'inst_synthetic',scope:'capture.only',challenge:'not-displayed-secret'};
for(const action of ['cancel','escape','accept']){
  let result=null;
  const pending=scope.test.confirmPairDestination(destination).then(value=>result=value);
  assert.equal(result,null);assert.equal(dialog.open,true);assert.equal(elements.pair.disabled,true);
  assert.equal(focus,'pair-confirm-cancel');
  assert.equal(elements['pair-confirm-destination'].textContent,'https://capture.test\ninst_synthetic\ncapture.only');
  assert.equal(elements['pair-confirm-destination'].textContent.includes(destination.challenge),false);
  if(action==='escape'){
    let prevented=false;dialog.oncancel({preventDefault:()=>prevented=true});assert(prevented);
  }
  else elements['pair-confirm-'+(action==='accept'?'accept':'cancel')].onclick();
  await pending;assert.equal(result,action==='accept');assert.equal(dialog.open,false);
  assert.equal(elements.pair.disabled,false);assert.equal(focus,'pair');
  assert.equal(elements['pair-confirm-accept'].onclick,null);
}
console.log(JSON.stringify({explicit_confirmation:true,escape_cancelled:true,secret_not_displayed:true}));
"""
    assert node(script)["explicit_confirmation"] is True



def test_install_guidance_waits_for_browser_choice_and_actual_installed_event():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync('core/provelume/static/capture-shell.js','utf8')
 .replace(/\}\)\(\);\s*$/, 'globalThis.test={setupInstallation};})();');
const listeners={}, elements={install:{hidden:true},'install-help':{hidden:true}};
const scope={navigator:{language:'en'},location:{protocol:'https:'},isSecureContext:true,
 document:{addEventListener(){},getElementById:id=>elements[id]},
 window:{addEventListener:(name,callback)=>listeners[name]=callback}};
vm.createContext(scope);vm.runInContext(source,scope);scope.test.setupInstallation();
let choose;const userChoice=new Promise(resolve=>choose=resolve);
listeners.beforeinstallprompt({preventDefault(){},prompt:async()=>{},userChoice});
assert.equal(elements.install.hidden,false);
assert.match(elements['install-help'].textContent,/address bar/);
const pendingInstall=elements.install.onclick();
assert.match(elements['install-help'].textContent,/Finish in/);
choose({outcome:'dismissed'});await pendingInstall;
assert.match(elements['install-help'].textContent,/cancelled/);
listeners.beforeinstallprompt({preventDefault(){},prompt:async()=>{},
 userChoice:Promise.resolve({outcome:'accepted'})});
await elements.install.onclick();await new Promise(resolve=>setImmediate(resolve));
assert.match(elements['install-help'].textContent,/accepted by the browser/);
listeners.appinstalled();
assert.match(elements['install-help'].textContent,/Capture installed/);
assert.equal(elements.install.hidden,true);
console.log(JSON.stringify({choice:true,installedEvent:true}));
"""
    assert node(script) == {"choice": True, "installedEvent": True}


def test_discarded_pairing_disables_new_capture_without_touching_pending_rows():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync('core/provelume/static/capture-shell.js','utf8')
 .replace(/\}\)\(\);\s*$/, 'globalThis.test={restorePairing,forgetPairing,limits,'+
 'state:()=>({auth,identity}),setCapabilities:v=>capabilities=v};})();');
const pending=[{id:'retained-request',payload_base64:'c3ludGhldGlj',device_id:'old-device'}];
const original=JSON.stringify(pending);
let saved={};const touched=[];
const db={transaction(store,mode){
 assert.equal(store,'settings');touched.push({store,mode});
 const tx={objectStore:()=>({
  get(key){const r={};queueMicrotask(()=>{r.result=saved[key];r.onsuccess();
   queueMicrotask(()=>tx.oncomplete());});return r;},
  delete(key){delete saved[key];queueMicrotask(()=>tx.oncomplete());}
 })};return tx;
}};
const elements=new Proxy({}, {get:(target,key)=>target[key]??=(key==='mode'?{value:'text'}:{})});
const scope={navigator:{language:'en'},location:{origin:'https://capture.test'},
 document:{addEventListener(){},getElementById:id=>elements[id]},queueMicrotask};
const injected=source.replace('async function restorePairing() {',
 'async function restorePairing() { db=globalThis.fakeDB;');
scope.fakeDB=db;vm.createContext(scope);vm.runInContext(injected,scope);
scope.test.setCapabilities({modes:{text:{types:['text/plain']}}});
for(const invalid of ['expired','foreign','missing']){
 saved={identity:{channel:'paired_pwa',device_id:'old-device'}};
 if(invalid!=='missing')saved.credential={channel:'paired_pwa',expiresAt:invalid==='expired'?0:Date.now()+10000,origin:invalid==='foreign'?'https://foreign.test':'https://capture.test'};
 await scope.test.restorePairing();scope.test.limits();
 assert.equal(scope.test.state().auth,null);assert.equal(scope.test.state().identity,null);
 assert.equal(elements.queue.disabled,true);assert.equal(saved.identity,undefined);
 assert.equal(saved.credential,undefined);assert.equal(JSON.stringify(pending),original);
}
saved={identity:{channel:'paired_pwa',device_id:'valid-device'},credential:{channel:'paired_pwa',expiresAt:Date.now()+10000,origin:'https://capture.test'}};
await scope.test.restorePairing();scope.test.limits();assert.equal(elements.queue.disabled,false);
await scope.test.forgetPairing();scope.test.limits();assert.equal(elements.queue.disabled,true);
assert.equal(JSON.stringify(pending),original);assert(touched.every(x=>x.store==='settings'));
console.log(JSON.stringify({invalid_pairing_disabled:true,pending_preserved:true}));
"""
    assert node(script) == {"invalid_pairing_disabled": True, "pending_preserved": True}

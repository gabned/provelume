"""Synthetic browser/worker execution; no claim of physical iOS/Android observation."""

import json
from pathlib import Path

from test_capture_shell_contract import node

ROOT = Path(__file__).resolve().parents[1]


def test_share_error_reads_only_existing_language_preference_and_falls_back_on_unavailable_store():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const handlers={};let choice='de',opened=0,closed=0,aborted=0;
const scope={URL,Response,TextEncoder,setTimeout,clearTimeout,
 self:{navigator:{language:'fr-FR'},location:{origin:'https://capture.test'},
 addEventListener:(k,v)=>handlers[k]=v,
 indexedDB:{open:(name,version)=>{
   assert.equal(name,'provelume-capture-outbox');assert.equal(version,1);opened++;
   const request={transaction:{abort(){aborted++;}}};
   queueMicrotask(()=>{
     if(choice==='missing'){request.onupgradeneeded();return;}
     request.result={close(){closed++;},objectStoreNames:{contains:n=>n==='settings'},
       transaction(store,mode){assert.equal(store,'settings');assert.equal(mode,'readonly');
         const transaction={objectStore:()=>({get(key){assert.equal(key,'language');
           const language={result:choice};
           queueMicrotask(()=>{language.onsuccess();transaction.oncomplete();});
           return language;}})};
         return transaction;}};
     request.onsuccess();
   });return request;
 }}}};
vm.createContext(scope);vm.runInContext(readFileSync('core/provelume/static/capture-worker.js','utf8')+
 ';self.test={shareLanguage,shareError};',scope);
assert.equal(await scope.self.test.shareLanguage(),'de');
assert.equal(closed,1);choice='system';assert.equal(await scope.self.test.shareLanguage(),'fr');
choice='missing';assert.equal(await scope.self.test.shareLanguage(),'fr');assert.equal(aborted,1);
choice='ro';const response=await scope.self.test.shareError(409);
assert.equal(response.status,409);assert.equal(response.headers.get('cache-control'),'no-store');
assert.match(await response.text(),/Partajare/);assert.equal(opened,4);assert.equal(closed,3);
console.log(JSON.stringify({preference_only:true,no_database_creation:true,localized_error:true}));
"""
    assert node(script)["localized_error"] is True


def test_android_manifest_and_transient_share_admission_without_second_store():
    manifest = json.loads((ROOT / "core/provelume/static/capture.webmanifest").read_text())
    assert manifest["share_target"]["action"] == "/capture/share"
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
const handlers={},messages=[];let now=0;
const scope={URL,Response,Request,Blob,TextEncoder,crypto:webcrypto,Date:{now:()=>now},
 setTimeout:()=>0,
 self:{location:{origin:'https://capture.test'},addEventListener:(k,v)=>handlers[k]=v}};
vm.createContext(scope);vm.runInContext(readFileSync('core/provelume/static/capture-worker.js','utf8'),scope);
async function share(fields){
 const form=new FormData();for(const [k,v] of fields)form.append(k,v);
 let response;handlers.fetch({request:new Request('https://capture.test/capture/share',
  {method:'POST',body:form}),respondWith:p=>response=p});return await response;
}
const source={url:'https://capture.test/capture/',postMessage:v=>messages.push(v)};
let response=await share([['text','<script>inert</script>']]);assert.equal(response.status,303);
assert.equal(response.headers.get('cache-control'),'no-store');
let id=new URL(response.headers.get('Location'),'https://capture.test').searchParams.get('share');
assert.equal((await share([['text','second pending item']])).status,409);
handlers.message({source:{...source,url:'https://foreign.test/capture/'},data:{kind:'capture-share',id}});
assert.equal(messages.length,0);
handlers.message({source,data:{kind:'capture-share',id:'wrong'}});assert.equal(messages.length,0);
handlers.message({source,data:{kind:'capture-share',id}});
assert.equal(messages[0].value.text,'<script>inert</script>');
handlers.message({source,data:{kind:'capture-share',id}});assert.equal(messages.length,1);
response=await share([['files',new Blob(['synthetic file'],{type:'text/plain'})]]);
assert.equal(response.status,303);id=new URL(response.headers.get('Location'),'https://capture.test').searchParams.get('share');
now=120001;handlers.message({source,data:{kind:'capture-share',id}});
assert.equal(messages[1].kind,'capture-share-expired');
assert.equal((await share([['files',new Blob(['a'])],['files',new Blob(['b'])]])).status,400);
assert.equal((await share([['text','x'.repeat(512*1024+1)]])).status,413);
assert.equal((await share([['credential','must never be a share field']])).status,400);
assert.equal((await share([])).status,400);
console.log(JSON.stringify({bounded:true,transient:true,one_use:true,foreign_rejected:true}));
"""
    assert node(script)["transient"] is True


def test_concurrent_share_does_not_overwrite_pending_handoff_and_failure_recovers():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
const handlers={},messages=[];
const scope={URL,Response,Request,Blob,TextEncoder,crypto:webcrypto,Date,setTimeout:()=>0,
 self:{location:{origin:'https://capture.test'},addEventListener:(k,v)=>handlers[k]=v}};
vm.createContext(scope);vm.runInContext(readFileSync('core/provelume/static/capture-worker.js','utf8'),scope);
const client={url:'https://capture.test/capture/',postMessage:v=>messages.push(v)};
function dispatch(request){let result;
 handlers.fetch({request,respondWith:p=>result=p});return result;}
function ordinary(text){const body=new FormData();body.append('text',text);
 return new Request('https://capture.test/capture/share',{method:'POST',body});}
const original=ordinary('first retained item');
let resume,reads=0,released=false;
const first=dispatch({url:original.url,method:'POST',headers:original.headers,
 body:{getReader:()=>({read:async()=>{if(reads++)return {done:true};
 await new Promise(r=>resume=r);
 return {done:false,value:new Uint8Array(await original.arrayBuffer())};},
 releaseLock:()=>released=true})}});
assert.equal((await dispatch(ordinary('second must be refused'))).status,409);
resume();const response=await first;assert.equal(response.status,303);assert.equal(released,true);
const id=new URL(response.headers.get('Location'),'https://capture.test').searchParams.get('share');
handlers.message({source:client,data:{kind:'capture-share',id}});
assert.equal(messages[0].value.text,'first retained item');
let failedReleased=false;
assert.equal((await dispatch({url:original.url,method:'POST',headers:original.headers,
 body:{getReader:()=>({read:async()=>{throw new Error('synthetic interrupted stream');},
 releaseLock:()=>failedReleased=true})}})).status,400);
assert.equal(failedReleased,true);
assert.equal((await dispatch(ordinary('recovered after interruption'))).status,303);
console.log(JSON.stringify({concurrent_refused:true,first_retained:true,recovery:true}));
"""
    assert node(script)["recovery"] is True


def test_retrieval_no_store_clear_and_stale_response_cannot_restore_content():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const elements=new Proxy({}, {get:(t,k)=>t[k]??={textContent:'',value:'',append(){}}});
let resolve,mode='delayed';const calls=[];
const source=readFileSync('core/provelume/static/capture-shell.js','utf8')
 .replace(/\}\)\(\);\s*$/, 'globalThis.test={knowledgeList,knowledgeRequest,clearKnowledge,'+
 'setAuth:a=>{auth=a;identity=a;},setGrant:v=>retrievalAuth=v,grant:()=>retrievalAuth};})();');
const scope={navigator:{language:'en'},location:{origin:'https://capture.test'},
 document:{addEventListener(){},getElementById:id=>elements[id]},AbortController,
 setTimeout,clearTimeout,
 fetch:async(url,options)=>{calls.push({url,options});
  if(mode==='denied')return {ok:false,status:403};
  await new Promise(r=>resolve=r);return {ok:true,json:async()=>({
    items:[{title:'<script>inert</script>',id:'doc_synthetic'}]})};}};
vm.createContext(scope);vm.runInContext(source,scope);
scope.test.setAuth({device_id:'dev_synthetic',instance_id:'inst_synthetic',channel:'paired_pwa',
 origin:'https://capture.test',expiresAt:Date.now()+600000,credential:'capture-only'});
scope.test.setGrant({device_id:'dev_synthetic',
 expires_at:new Date(Date.now()+600000).toISOString(),credential:'read-only'});
const pending=scope.test.knowledgeList();await new Promise(r=>setImmediate(r));
assert.equal(calls[0].options.credentials,'omit');assert.equal(calls[0].options.cache,'no-store');
assert.equal(calls[0].options.headers.Authorization,'Bearer read-only');
assert.equal(calls[0].options.headers['X-Retrieval-Device'],'dev_synthetic');
assert.equal(calls[0].url.includes('credential'),false);
elements['retrieval-detail'].textContent='private content';
elements['retrieval-query'].value='private query';
scope.test.clearKnowledge();resolve();await pending;
assert.equal(scope.test.grant(),null);assert.equal(elements['retrieval-detail'].textContent,'');
assert.equal(elements['retrieval-query'].value,'');assert.equal(elements['retrieval-results'].textContent,'');
await assert.rejects(scope.test.knowledgeRequest('/recent'),/expired/);
mode='denied';scope.test.setGrant({device_id:'dev_synthetic',
 expires_at:new Date(Date.now()+600000).toISOString(),credential:'revoked'});
await assert.rejects(scope.test.knowledgeRequest('/recent'),/revoked/);
console.log(JSON.stringify({no_store:true,separate_token:true,cleared:true,stale_rejected:true}));
"""
    assert node(script)["stale_rejected"] is True


def test_existing_retrieval_results_errors_and_version_identity_change_language():
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const nodes=[];
function element(){const e={dataset:{},textContent:'',value:'',children:[],
 append(...v){this.children.push(...v);}};nodes.push(e);return e;}
const elements=new Proxy({}, {get:(t,k)=>t[k]??=element()});
let mode='recent';const version='ver_'+'9'.repeat(32);
const source=readFileSync('core/provelume/static/capture-shell.js','utf8')
 .replace(/\}\)\(\);\s*$/, 'globalThis.test={knowledgeList,knowledgeDetail,'+
 'knowledgeAction,knowledgeRequest,'+
 'setLanguage:l=>{lang=l;translate();},setAuth:a=>{auth=a;identity=a;}};})();');
const scope={navigator:{language:'en'},location:{origin:'https://capture.test',protocol:'https:'},
 isSecureContext:true,AbortController,setTimeout,clearTimeout,
 document:{documentElement:{},addEventListener(){},getElementById:id=>elements[id],
  createElement:element,querySelectorAll:selector=>selector==='[data-i18n]'?nodes.filter(n=>n.dataset.i18n):[]},
 fetch:async()=> mode==='denied'?{ok:false,status:403}:{ok:true,json:async()=>mode==='recent'
  ?{items:[{title:'synthetic',id:'doc_synthetic'}]}
  :{versions:[{id:version}],grant:{source_ids:['src_synthetic'],expires_at:'local session'}}}};
vm.createContext(scope);vm.runInContext(source,scope);
scope.test.setAuth({device_id:'dev_synthetic',instance_id:'inst_synthetic',channel:'local_browser',
 expiresAt:Date.now()+600000});
await scope.test.knowledgeList();
const preview=elements['retrieval-results'].children[0].children[1];
assert.equal(preview.textContent,'Preview provenance and versions');
scope.test.setLanguage('it');
assert.equal(preview.textContent,'Anteprima di provenienza e versioni');
assert.equal(elements['retrieval-status'].textContent,'Consulta Knowledge');
mode='detail';await scope.test.knowledgeDetail('doc_synthetic');
const download=elements['retrieval-downloads'].children[0];
assert.equal(download.textContent,'Scarica questo Originale esatto (allegato) '+version);
scope.test.setLanguage('en');
assert.equal(download.textContent,'Download this exact Original (attachment) '+version);
assert.match(elements['retrieval-status'].textContent,/Separate Knowledge grant active/);
assert.match(elements['retrieval-status'].textContent,/src_synthetic/);
mode='denied';await scope.test.knowledgeAction(()=>scope.test.knowledgeRequest('/recent'));
assert.match(elements['retrieval-status'].textContent,/revoked.*\(403\)/);
scope.test.setLanguage('it');
assert.match(elements['retrieval-status'].textContent,/revocato.*\(403\)/);
console.log(JSON.stringify({live_language:true,version_preserved:true,error_translated:true}));
"""
    assert node(script)["live_language"] is True

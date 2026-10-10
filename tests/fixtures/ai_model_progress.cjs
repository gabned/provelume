const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const timers = new Map(), requests = [], listeners = {}, windowListeners = {};
  let next = 0;
  const node = () => ({textContent:'', value:'', dataset:{}, removeAttribute(key) {delete this[key];}});
  const notice=node(), manual=node(), bytes=node(), progress=node(), phase=node(), nonce=node(), cancel=node();
  const operation=node(); operation.querySelector=()=>bytes;
  manual.addEventListener=(_, callback)=>{manual.click=callback;};
  const fields = {'[data-ai-refresh-status]':notice,'[data-ai-refresh]':manual,
    '[data-ai-phase]':phase,'#ai-model-operation':operation,'[data-ai-progress]':progress,
    '#ai-model-actions input[name="mutation_nonce"]':nonce,'#ai-model-actions button':cancel};
  const root={dataset:{state:'running',url:'/settings/ai/model/status?lang=en',
    instance:'instance',session:'session',operation:'operation',unavailable:'unavailable',
    stale:'stale',running:'running',verifying:'verifying',cancelling:'cancelling'},
    querySelector:key=>fields[key]};
  const document={hidden:false,documentElement:{lang:'en'},querySelector:()=>root,
    addEventListener:(name,callback)=>{listeners[name]=callback;}};
  const window={addEventListener:(name,callback)=>{windowListeners[name]=callback;}};
  vm.runInNewContext(source,{document,window,URL,Intl,AbortController,location:{origin:'http://localhost'},
    setTimeout:(callback,delay)=>{timers.set(++next,{callback,delay});return next;},
    clearTimeout:id=>timers.delete(id),
    fetch:(url,options)=>new Promise((resolve,reject)=>{
      assert.equal(url.origin,'http://localhost');assert.equal(options.cache,'no-store');
      assert.equal(options.redirect,'error');assert.equal(options.method,undefined);
      assert.equal(url.searchParams.get('operation'),'operation');
      requests.push({resolve,reject,options});options.signal.addEventListener('abort',()=>reject(new Error('aborted')));
    })});
  const tick=async()=>{
    const [id,timer]=timers.entries().next().value;timers.delete(id);timer.callback();await settle();
  };
  const reply=async(value={},status=200)=>{
    requests.at(-1).resolve({ok:status===200,status,json:async()=>({instance:'instance',session:'session',
      operation:'operation',state:'running',bytes:12001672,total:1440000000,action:'install',
      cancel_requested:false,cancel_nonce:'fresh',...value})});await settle();
  };
  return {timers,requests,listeners,windowListeners,document,root,notice,manual,bytes,progress,
    phase,nonce,cancel,operation,tick,reply};
}
(async()=>{
  let f=fixture();await f.tick();await f.reply();
  assert.equal(f.bytes.textContent,'12.00 MB'.replace('12.00','12'));
  assert.equal(f.progress.value,12001672);assert.equal(f.nonce.value,'fresh');
  assert.equal(f.phase.textContent,'running');assert.equal(f.timers.size,1);
  await f.tick();await f.reply({bytes:1440000000});
  assert.equal(f.progress.value,undefined);assert.equal(f.phase.textContent,'verifying');
  await f.tick();await f.reply({cancel_requested:true});assert.equal(f.phase.textContent,'cancelling');
  assert.equal(f.cancel.disabled,true);
  await f.tick();const count=f.requests.length;
  f.manual.click({preventDefault(){}});assert.equal(f.requests.length,count);
  f.requests.at(-1).reject(new Error('offline'));await settle();
  assert.equal(f.notice.textContent,'unavailable');assert.equal([...f.timers.values()][0].delay,4000);
  await f.tick();await f.reply();assert.equal(f.notice.textContent,'');
  assert.equal([...f.timers.values()][0].delay,2000);
  await f.tick();await f.reply({},409);assert.equal(f.notice.textContent,'stale');assert.equal(f.timers.size,0);
  let prevented=false;f.manual.click({preventDefault(){prevented=true;}});assert.equal(prevented,false);
  f=fixture();await f.tick();await f.reply({session:'old-service'});
  assert.equal(f.notice.textContent,'stale');assert.equal(f.timers.size,0);
  f=fixture();await f.tick();f.document.hidden=true;f.listeners.visibilitychange();await settle();
  assert.equal(f.requests[0].options.signal.aborted,true);assert.equal(f.notice.textContent,'');
  assert.equal(f.timers.size,0);
  f.document.hidden=false;f.listeners.visibilitychange();await f.tick();await f.reply();
  assert.equal(f.requests.length,2);
  await f.tick();f.windowListeners.pagehide();await settle();assert.equal(f.timers.size,0);
  f.windowListeners.pageshow();await f.tick();await f.reply();assert.equal(f.timers.size,1);
  console.log('Read-only AI progress, backoff, identity, nonce and lifecycle contracts passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

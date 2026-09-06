import test from "node:test";
import assert from "node:assert/strict";
import {collectSource, collectPreflight} from "../tools/agent_protocol_work_collect.mjs";

const repo = "example/public", base = "a".repeat(40), root = "b".repeat(40), blob = "c".repeat(40);
const ref = {ref:"refs/heads/main", object:{type:"commit", sha:base}};
const entries = [{path:"readme", type:"blob", mode:"100644", sha:blob, size:1}];
function host(overrides = {}) {
  const calls = [], saves = [];
  const values = {
    "":{full_name:repo, default_branch:"main"},
    "/git/ref/heads/main":ref,
    [`/git/commits/${base}`]:{sha:base, tree:{sha:root}, message:"a normal commit message"},
    [`/git/trees/${root}?recursive=1`]:{sha:root, tree:entries, truncated:false},
    [`/git/blobs/${blob}`]:{sha:blob, size:1, encoding:"base64", content:"eA=="},
    ...overrides,
  };
  const prefix = `https://api.github.com/repos/${repo}`;
  return {calls, saves, repository:repo, now:()=>"2026-09-06T00:00:00Z",
    fetchJson:async url=>{assert.ok(url.startsWith(prefix));const key=url.slice(prefix.length);calls.push(key);
      const value=values[key]; if(value instanceof Error) throw value;
      assert.notEqual(value,undefined,`unexpected connector read: ${key}`);
      return typeof value === "function" ? value() : structuredClone(value);},
    saveBlob:async (sha,response)=>saves.push({sha,response})};
}
test("complete capture uses connector reads and preserves binary transport", async()=>{
  const h=host();const r=await collectSource(h);
  assert.equal(r.snapshot.commit_sha,base);assert.equal(h.saves.length,1);
  assert.equal(r.acquisition.push_qualified,false);assert.equal(h.calls.at(-1),"/git/ref/heads/main");
});
test("verified cache still requires final offline content verification", async()=>{
  const h=host();h.hasBlob=async()=>true;const r=await collectSource(h);
  assert.equal(r.acquisition.cached_blobs,1);assert.equal(h.saves.length,0);
});
test("moved default blocks", async()=>{
  let reads=0;const h=host({"/git/ref/heads/main":()=>++reads===1?ref:{...ref,object:{type:"commit",sha:"d".repeat(40)}}});
  await assert.rejects(collectSource(h),/default moved/);
});
test("truncated recursive tree is reconstructed through nonrecursive reads", async()=>{
  const sub="d".repeat(40);
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,tree:[],truncated:true},
    [`/git/trees/${root}`]:{sha:root,tree:[{path:"src",type:"tree",mode:"040000",sha:sub}],truncated:false},
    [`/git/trees/${sub}`]:{sha:sub,tree:entries,truncated:false}});
  const r=await collectSource(h);assert.deepEqual(r.snapshot.tree.tree.map(x=>x.path),["src","src/readme"]);
});
test("truncated nonrecursive response blocks", async()=>{
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:true},[`/git/trees/${root}`]:{sha:root,tree:entries,truncated:true}});
  await assert.rejects(collectSource(h),/incomplete subtree/);
});
test("no credential or network fallback on connector failure", async()=>{
  await assert.rejects(collectSource(host({[`/git/blobs/${blob}`]:new Error("denied")})),/denied/);
});
test("bounded request budget", async()=>{await assert.rejects(collectSource({...host(),maxCalls:1}),/budget/);});
test("non-finite and non-integer request budgets fail before access", async()=>{
  for (const maxCalls of [Infinity, NaN, 0, 1.5, 10001]) {
    const h=host();
    await assert.rejects(collectSource({...h,maxCalls}),/budget/);
    assert.equal(h.calls.length,0);
  }
});
test("source anchor retains authoritative default-branch metadata", async()=>{
  const r=await collectSource(host());
  assert.equal(r.anchor.repository.response.full_name,repo);
  assert.equal(r.anchor.repository.response.default_branch,"main");
});
test("object identity is validated before any blob URL is requested", async()=>{
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,
    tree:[{...entries[0],sha:"../not-an-object"}]}});
  await assert.rejects(collectSource(h),/object identity/);
  assert.equal(h.calls.some(x=>x.includes("/git/blobs/")),false);
});
test("symlink/submodule cannot silently disappear", async()=>{
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,tree:[{...entries[0],mode:"120000"}]}});
  await assert.rejects(collectSource(h),/adapter unavailable/);
});
function preflightHost(overrides={}) {
  return host({"/branches/main":{name:"main",commit:{sha:base},protected:false},
    "/rulesets?includes_parents=true&per_page=100&page=1":[],
    "/pulls?state=open&per_page=100&page=1":[],
    "/actions/runs?per_page=20&page=1":{workflow_runs:[]},...overrides});
}
test("non-finite pagination budgets fail before access",async()=>{
  const h=preflightHost();
  await assert.rejects(collectPreflight({...h,maxPages:Infinity}),/budget/);
  assert.equal(h.calls.length,0);
});
test("observational preflight does not become CI qualification",async()=>{
  const r=await collectPreflight(preflightHost());assert.equal(r.open_pull_requests.complete,true);
  assert.equal(r.push_qualified,false);assert.equal(r.environments,"UNKNOWN_NOT_ACCESSED");
});
test("policy denied remains UNKNOWN",async()=>{
  const r=await collectPreflight(preflightHost({"/rulesets?includes_parents=true&per_page=100&page=1":new Error("denied")}));
  assert.equal(r.rulesets.status,"UNKNOWN");assert.equal(r.rulesets.complete,false);
});
test("open PR pagination is bounded and never claimed complete at cap",async()=>{
  const h=preflightHost({"/pulls?state=open&per_page=100&page=1":Array.from({length:100},(_,i)=>({number:i+1}))});
  const r=await collectPreflight({...h,maxPages:1});assert.equal(r.open_pull_requests.complete,false);
});
test("only selected PR gets detail and missing threads remain UNKNOWN",async()=>{
  const h=preflightHost({"/pulls/1":{number:1,state:"open"},"/pulls/1/reviews?per_page=100&page=1":[]});
  const r=await collectPreflight({...h,activePr:1});assert.equal(r.active_pull_request.threads.status,"UNKNOWN");
});

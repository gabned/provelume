"use strict";
const CACHE = "provelume-capture-public-__CAPTURE_SHELL_REVISION__";
const PUBLIC = ["/capture/", "/capture/shell.js", "/capture/style.css", "/capture/manifest.webmanifest", "/capture/icon.svg", "/capture/icon192.png", "/capture/icon512.png"];
const MAX_FILE = 256 * 1024;
// Transient handoff only. Durable admission uses the shell's existing S06 outbox.
let shared = null;
const SHARE_LIMIT = 25 * 1024 * 1024 + 16384;
const shareError = status => new Response("Share unavailable or interrupted. Keep the source item and use Capture file selection or the configured Drive-drop folder.", {status, headers:{"Content-Type":"text/plain; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
async function receiveShare(request) {
  if (shared && shared.expires > Date.now()) return shareError(409);
  shared=null;
  if (!request.headers.get("Content-Type")?.startsWith("multipart/form-data;")) return shareError(415);
  const reader=request.body?.getReader(); if(!reader)return shareError(400);
  let size=0;const chunks=[];
  try {
    while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>SHARE_LIMIT){await reader.cancel();return shareError(413);}chunks.push(value);}
    const form=await new Response(new Blob(chunks),{headers:{"Content-Type":request.headers.get("Content-Type")}}).formData();
    if([...form.keys()].some(k=>!["title","text","url","files"].includes(k)))return shareError(400);
    const files=form.getAll("files");if(files.length>1)return shareError(400);
    const value={};for(const key of ["title","text","url"]){const entries=form.getAll(key);if(entries.length>1||entries.some(v=>typeof v!=="string"))return shareError(400);value[key]=entries[0]||"";}
    if(value.title.length>512||new TextEncoder().encode(value.text).length>512*1024||new TextEncoder().encode(value.url).length>8192)return shareError(413);
    if(files.length&&(!(files[0] instanceof Blob)||files[0].size>25*1024*1024))return shareError(413);
    if(!files.length&&!value.text&&!value.url&&!value.title)return shareError(400);
    const id=crypto.randomUUID();shared={id,value:{...value,file:files[0]||null},expires:Date.now()+120000};
    const selected=shared;setTimeout(()=>{if(shared===selected)shared=null;},120000);
    return new Response(null,{status:303,headers:{Location:"/capture/?share="+id,"Cache-Control":"no-store"}});
  }catch(error){shared=null;return shareError(400);}
}
self.addEventListener("message",event=>{
  const client=event.source;
  if(!client||!shared||event.data?.kind!=="capture-share"||event.data.id!==shared.id)return;
  const url=new URL(client.url);
  if(url.origin!==self.location.origin||url.pathname!=="/capture/")return;
  if(shared.expires<=Date.now()){shared=null;client.postMessage({kind:"capture-share-expired"});return;}
  client.postMessage({kind:"capture-share",value:shared.value});shared=null;
});
self.addEventListener("install", event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  for (const path of PUBLIC) {
    const response = await fetch(path, {credentials: "omit", cache: "no-store"});
    if (!response.ok || response.headers.has("Set-Cookie")) throw new Error("Public shell unavailable");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > MAX_FILE) throw new Error("Public shell size bound");
    await cache.put(path, new Response(bytes, {status: 200, headers: response.headers}));
  }
})()));
self.addEventListener("activate", event => event.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith("provelume-capture-public-") && key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if(request.method==="POST"&&url.origin===self.location.origin&&url.pathname==="/capture/share"&&!url.search){event.respondWith(receiveShare(request));return;}
  if (request.method !== "GET" || url.origin !== self.location.origin || url.search ||
      !PUBLIC.includes(url.pathname) || request.headers.has("Authorization") || request.headers.has("X-Capture-Nonce")) return;
  event.respondWith((async () => {
    try { return await fetch(request); }
    catch (error) { const saved = await caches.match(url.pathname, {cacheName: CACHE}); if (saved) return saved; throw error; }
  })());
});

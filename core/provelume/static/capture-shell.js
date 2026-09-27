"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const WORDS = {
    en: {
      installReady:"Install Capture as an app. After clicking, look for the browser's installation dialog near the address bar; it may be behind this window. Confirm Install there.",
      installPrompt:"Finish in the browser's installation dialog near the address bar. If it is hidden, bring this browser window to the front. Capture stays usable if you cancel.",
      installAccepted:"Installation accepted by the browser. Open Capture from your apps and check that it opens in its own window without an address bar.",
      installDismissed:"Installation cancelled. Capture and your local outbox remain usable. Use the browser's install menu to try again.",
      installComplete:"Capture installed. Open it from your apps; its own window has no browser address bar.",
      title:"Capture",language:"Language",boundary:"Originals remain untrusted. Files are not executed or scanned for malware. Downloads are explicit attachments.",
      connection:"Connection",connect:"Connect local Capture",pairCode:"Pairing QR contents",deviceLabel:"Device name",retain:"Keep scoped pairing on this browser for at most 30 days. Never shared with the worker cache.",pair:"Pair this device",scanQr:"Scan pairing QR",forget:"Forget local pairing",install:"Install Capture",newCapture:"Add a capture",mode:"Mode",file:"File",photo:"Photo",scan:"Scan",screenshot:"Screenshot",url:"Link (no fetching)",text:"Text",audio:"Audio (PCM16 WAV)",voice:"Voice note",chooseFile:"Choose one file",content:"Text or one HTTP(S) link",camera:"Start camera",snapshot:"Take photo / scan",record:"Record voice note",stop:"Stop media capture",note:"Note (optional)",area:"Area proposal (optional reference)",project:"Project proposal (optional reference)",proposal:"Proposals do not classify or create Claims, Decisions, Tasks or Calendar Events. Existing review permissions govern subsequent routing.",queue:"Queue and send",outbox:"Local outbox",retention:"At most 16 items / 64 MiB. Pending bytes remain locally until an authoritative receipt. Acknowledgement removes pending bytes, not server knowledge. Local removal never cancels an accepted server submission.",retryAll:"Reconcile / retry queued captures",receipts:"Refresh my server receipts",owner:"Local owner: devices and retained captures",httpsHelp:"Remote Capture is a separate listener, disabled by default. Configure its exact HTTPS origin, then start it explicitly with a certificate. Management remains loopback-only. QR challenges expire in 120 seconds and are single-use.",origin:"Trusted HTTPS Capture origin",rebind:"Configure / rebind this destination and revoke existing credentials. Acquired knowledge is retained.",configure:"Configure destination",createQr:"Create one-use pairing QR",ownerRefresh:"Refresh retained Capture results",quarantineHelp:"Rejection records quarantine with explicit retention. Undo records compensation. Neither action moves or purges Originals or canonical history. Archive/trash/purge remain separate governed Knowledge actions.",backInbox:"Return to local Inbox",
      fallback:"Plain HTTP fallback: PWA installation, workers and share targets disabled. Local Capture still works.",secure:"Secure Capture surface. Only public shell resources may enter the worker cache; knowledge caching is disabled.",offline:"Offline: local queued captures are not yet acquired.",connected:"Connected. Local queued captures retain their original device/Instance identity.",pairNeeded:"Connect / pair before sending. Pending captures remain local.",queued:"queued, not acquired",sending:"sending; server outcome not yet known",acknowledged:"acknowledged submission; processing separate",attention:"attention",acquired:"acquired",localOnly:"Local removal cannot cancel a server submission or delete acquired knowledge. Remove this local copy?",forgetConfirm:"Forget this browser's pairing credential? Pending captures and acquired server knowledge remain.",storage:"Local storage/quota unavailable. No capture was acknowledged or silently discarded.",wrongDevice:"The saved capture belongs to another device/Instance. It cannot be resubmitted under a new identity.",uncertain:"Outcome uncertain: authoritative receipt must be reconciled before retry.",mediaReady:"Media is local and not queued. Press Queue and send to retain it.",mediaDenied:"Camera/microphone permission denied or unavailable; use a supported file instead.",mediaUnsupported:"This media capability is unavailable in this browser/context.",micActive:"Recording locally (maximum 90 seconds). Stop to retain a WAV, then queue it.",cameraActive:"Camera is local only. Take a snapshot; no upload occurs before Queue and send.",limits:"Limits declared before selection",empty:"No local captures.",retry:"Reconcile / retry",remove:"Remove local copy",download:"Download own Original (attachment)",revoke:"Revoke device",quarantine:"Reject / quarantine",undo:"Undo quarantine",days:"Retention days (1–365; no automatic purge)",retained:"Original and history retained",paired:"Paired. The credential is Capture-scoped; owner administration is not available here.",retainRequired:"Choose explicitly whether to retain pairing before redemption; this outbox needs durable pairing across reload.",qrUnavailable:"QR scanner unavailable. Copy the QR contents from local owner management.",failed:"Capture action failed: ",qrExpiry:"One-use QR expires in 120 seconds. Destination, Instance and scope are in its contents.",installUnavailable:"PWA installation unavailable; Capture and the bounded outbox remain usable.",installed:"Capture worker ready; authenticated responses are never cached.",ownerDone:"Owner action recorded. Refresh the retained result before any retry.",unsupported:"Selected capture is outside the declared type/byte/capability matrix.",payloadChanged:"Receipt fingerprint/device does not match this queued capture; do not resubmit.",confirmPair:"Pair this device with the displayed destination/Instance and only the displayed Capture scope?"
    },
    it: {
      installReady:"Installa Capture come app. Dopo il clic, cerca il dialogo di installazione del browser vicino alla barra degli indirizzi: potrebbe essere dietro questa finestra. Conferma Installa nel dialogo.",
      installPrompt:"Completa l'installazione nel dialogo del browser vicino alla barra degli indirizzi. Se è nascosto, porta questa finestra del browser in primo piano. Capture resta utilizzabile se annulli.",
      installAccepted:"Il browser ha accettato l'installazione. Apri Capture dalle tue app e verifica che si apra in una finestra propria senza barra degli indirizzi.",
      installDismissed:"Installazione annullata. Capture e la coda locale restano utilizzabili. Puoi riprovare dal menu di installazione del browser.",
      installComplete:"Capture installata. Aprila dalle tue app: la sua finestra non ha la barra degli indirizzi del browser.",
      title:"Acquisisci",language:"Lingua",boundary:"Gli Original restano non attendibili. I file non vengono eseguiti né sottoposti a scansione antivirus. Il download è un allegato esplicito.",connection:"Connessione",connect:"Connetti Capture locale",pairCode:"Contenuto del QR di abbinamento",deviceLabel:"Nome del dispositivo",retain:"Conserva l'abbinamento limitato su questo browser per massimo 30 giorni. Mai nella cache del worker.",pair:"Abbina questo dispositivo",scanQr:"Scansiona il QR di abbinamento",forget:"Dimentica l'abbinamento locale",install:"Installa Capture",newCapture:"Aggiungi un'acquisizione",mode:"Modalità",file:"File",photo:"Foto",scan:"Scansione",screenshot:"Screenshot",url:"Link (senza recupero remoto)",text:"Testo",audio:"Audio (WAV PCM16)",voice:"Nota vocale",chooseFile:"Scegli un solo file",content:"Testo oppure un solo link HTTP(S)",camera:"Avvia fotocamera",snapshot:"Scatta foto / scansione",record:"Registra nota vocale",stop:"Interrompi acquisizione multimediale",note:"Nota (facoltativa)",area:"Proposta Area (riferimento facoltativo)",project:"Proposta Project (riferimento facoltativo)",proposal:"Le proposte non classificano e non creano Claims, Decisions, Tasks o Calendar Events. Il routing successivo usa i permessi di revisione esistenti.",queue:"Accoda e invia",outbox:"Coda locale",retention:"Massimo 16 elementi / 64 MiB. I byte pendenti restano locali fino alla ricevuta autorevole. La conferma elimina i byte pendenti, non la conoscenza sul server. Rimuovere la copia locale non annulla un invio già accettato.",retryAll:"Riconcilia / riprova gli invii in coda",receipts:"Aggiorna le mie ricevute server",owner:"Owner locale: dispositivi e acquisizioni conservate",httpsHelp:"Capture remoto usa un listener separato, disabilitato per impostazione predefinita. Configura la sua origin HTTPS esatta, poi avvialo esplicitamente con un certificato. La gestione resta solo loopback. Il QR scade in 120 secondi ed è monouso.",origin:"Origin HTTPS attendibile per Capture",rebind:"Configura / riassocia questa destinazione e revoca le credenziali esistenti. La conoscenza acquisita viene conservata.",configure:"Configura destinazione",createQr:"Crea QR di abbinamento monouso",ownerRefresh:"Aggiorna i risultati Capture conservati",quarantineHelp:"Il rifiuto registra quarantena con conservazione esplicita. Annulla registra una compensazione. Nessuna azione sposta o elimina Original e storia canonica. Archivio/cestino/eliminazione restano azioni distinte e governate in Knowledge.",backInbox:"Torna all'Inbox locale",fallback:"Fallback HTTP: installazione PWA, worker e share target disabilitati. Capture locale resta utilizzabile.",secure:"Capture sicuro. Solo la shell pubblica entra nella cache del worker; la cache della conoscenza è disabilitata.",offline:"Offline: gli elementi nella coda locale non sono ancora acquisiti.",connected:"Connesso. La coda locale conserva l'identità originale di dispositivo e Instance.",pairNeeded:"Connetti / abbina prima di inviare. Gli elementi pendenti restano locali.",queued:"in coda, non acquisito",sending:"invio in corso; esito server non ancora noto",acknowledged:"invio confermato; elaborazione distinta",attention:"richiede attenzione",acquired:"acquisito",localOnly:"La rimozione locale non annulla un invio server e non elimina la conoscenza acquisita. Rimuovere questa copia locale?",forgetConfirm:"Dimenticare la credenziale di abbinamento di questo browser? Invii pendenti e conoscenza acquisita sul server restano conservati.",storage:"Memoria locale o quota non disponibile. Nessun invio è stato confermato o scartato silenziosamente.",wrongDevice:"L'elemento salvato appartiene a un altro dispositivo/Instance. Non può essere reinviato con una nuova identità.",uncertain:"Esito incerto: riconciliare la ricevuta autorevole prima di riprovare.",mediaReady:"Il contenuto è locale e non accodato. Premi Accoda e invia per conservarlo.",mediaDenied:"Permesso fotocamera/microfono negato o non disponibile; usa un file supportato.",mediaUnsupported:"Questa funzionalità multimediale non è disponibile nel browser o contesto corrente.",micActive:"Registrazione locale (massimo 90 secondi). Interrompi per conservare il WAV, poi accodalo.",cameraActive:"La fotocamera è solo locale. Scatta un'immagine; nessun upload precede Accoda e invia.",limits:"Limiti dichiarati prima della selezione",empty:"Nessun elemento locale.",retry:"Riconcilia / riprova",remove:"Rimuovi copia locale",download:"Scarica il tuo Original (allegato)",revoke:"Revoca dispositivo",quarantine:"Rifiuta / quarantena",undo:"Annulla quarantena",days:"Giorni di conservazione (1–365; nessuna eliminazione automatica)",retained:"Original e storia conservati",paired:"Abbinato. La credenziale è limitata a Capture; qui la gestione owner non è disponibile.",retainRequired:"Scegli esplicitamente la conservazione dell'abbinamento prima di usarlo; questa coda richiede un abbinamento durevole dopo il reload.",qrUnavailable:"Scanner QR non disponibile. Copia il contenuto del QR dalla gestione owner locale.",failed:"Azione Capture non riuscita: ",qrExpiry:"Il QR monouso scade in 120 secondi. Contiene destinazione, Instance e scope.",installUnavailable:"Installazione PWA non disponibile; Capture e coda limitata restano utilizzabili.",installed:"Worker Capture pronto; le risposte autenticate non vengono mai memorizzate in cache.",ownerDone:"Azione owner registrata. Aggiorna il risultato conservato prima di riprovare.",unsupported:"L'elemento selezionato non rispetta tipi, byte o funzionalità dichiarati.",payloadChanged:"Fingerprint/dispositivo della ricevuta non corrisponde alla coda; non reinviare.",confirmPair:"Abbinare questo dispositivo alla destinazione/Instance mostrate e solo allo scope Capture indicato?"
    }
  };
  let lang = navigator.language?.toLowerCase().startsWith("it")?"it":"en", db, auth = null, identity = null, capabilities = null, flushActive = false;
  const updates = typeof BroadcastChannel === "function" ? new BroadcastChannel("provelume-capture-outbox-changed") : null;
  let media = null, stream = null, recorder = null, installEvent = null, qrUrl = null, installState = null;
  const MAX_ITEMS = 16, MAX_BYTES = 64 * 1024 * 1024;
  let statusKey = null, statusExtra = "";
  const say = (key, extra="") => { statusKey=key;statusExtra=extra;$("status").textContent = WORDS[lang][key] + extra; };
  const canonical = value => JSON.stringify(Object.fromEntries(Object.keys(value).sort().map(k => [k,value[k]])));
  const uuid = () => crypto.randomUUID();
  const bytes64 = bytes => { let value=""; for(let p=0;p<bytes.length;p+=8192) value+=String.fromCharCode(...bytes.subarray(p,p+8192)); return btoa(value); };
  async function fingerprint(bytes, metadata) {
    const encoded = new TextEncoder().encode(canonical(metadata));
    const input = new Uint8Array(8+encoded.length+bytes.length);
    new DataView(input.buffer).setBigUint64(0, BigInt(encoded.length));
    input.set(encoded,8); input.set(bytes,8+encoded.length);
    return [...new Uint8Array(await crypto.subtle.digest("SHA-256",input))].map(v=>v.toString(16).padStart(2,"0")).join("");
  }
  function openDB() {
    return new Promise((resolve,reject) => {
      const request=indexedDB.open("provelume-capture-outbox",1);
      request.onupgradeneeded=()=>{ request.result.createObjectStore("items",{keyPath:"id"}); request.result.createObjectStore("settings"); };
      request.onsuccess=()=>resolve(request.result); request.onerror=()=>reject(new Error(WORDS[lang].storage));
      request.onblocked=()=>reject(new Error(WORDS[lang].storage));
    });
  }
  function transaction(store, mode, operation) {
    return new Promise((resolve,reject) => {
      const tx=db.transaction(store,mode), selected=tx.objectStore(store); let result;
      operation(selected,value=>{result=value;});
      tx.oncomplete=()=>{if(store==="items"&&mode==="readwrite")updates?.postMessage({kind:"changed"});resolve(result);}; tx.onerror=tx.onabort=()=>reject(new Error(WORDS[lang].storage));
    });
  }
  const setting = key => transaction("settings","readonly",(store,done)=>{const r=store.get(key);r.onsuccess=()=>done(r.result);});
  const saveSetting = (key,value) => transaction("settings","readwrite",store=>value===undefined?store.delete(key):store.put(value,key));
  function validEntry(row) {
    return row&&row.schema_version===1&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.id)
      &&/^dev_[0-9a-f]{32}$/.test(row.device_id)&&/^inst_[0-9a-f]{32}$/.test(row.instance_id)&&/^[0-9a-f]{64}$/.test(row.fingerprint)
      &&["queued","sending","acknowledged","acquired","attention"].includes(row.state)&&["local_browser","paired_pwa"].includes(row.channel)
      &&Number.isSafeInteger(row.byteSize)&&row.byteSize>=0&&row.byteSize<=36*1024*1024&&Number.isSafeInteger(row.createdAt)&&Number.isSafeInteger(row.lease)
      &&(row.payload_base64===null||(typeof row.payload_base64==="string"&&row.payload_base64.length<=35*1024*1024));
  }
  const entries = async () => {
    const rows=await transaction("items","readonly",(store,done)=>{const r=store.getAll();r.onsuccess=()=>done(r.result);});
    if(rows.length>MAX_ITEMS||rows.some(r=>!validEntry(r))||rows.reduce((n,r)=>n+r.byteSize,0)>MAX_BYTES)throw new Error(WORDS[lang].storage);
    return rows;
  };
  const change = (id, update) => transaction("items","readwrite",(store,done)=>{const r=store.get(id);r.onsuccess=()=>{if(!r.result){done(null);return;}const row=update(r.result);if(row)store.put(row);else store.delete(id);done(row);};});
  const headers = () => auth?.channel==="paired_pwa"?{"Authorization":"Bearer "+auth.credential,"X-Capture-Device":auth.device_id}:{"X-Capture-Nonce":auth?.nonce||""};
  async function api(path, data, {anonymous=false}={}) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch("/capture"+path,{method:data===undefined?"GET":"POST",credentials:"omit",cache:"no-store",signal:controller.signal,headers:{...(anonymous?{}:headers()),...(data===undefined?{}:{"Content-Type":"application/json"})},...(data===undefined?{}:{body:JSON.stringify(data)})});
      const value=await response.json();
      if(!response.ok){const error=new Error(value.detail||WORDS[lang].uncertain);error.status=response.status;throw error;}
      return value;
    } finally { clearTimeout(timer); }
  }
  function button(key, action) { const b=document.createElement("button");b.type="button";b.textContent=WORDS[lang][key];b.onclick=()=>run(action);return b; }
  async function run(action) { try { await action(); } catch(error) { say("failed",error.message); } }
  function translate() {
    document.documentElement.lang=lang;
    for(const e of document.querySelectorAll("[data-i18n]")) e.textContent=WORDS[lang][e.dataset.i18n];
    $("transport").textContent=WORDS[lang][location.protocol==="https:"&&isSecureContext?"secure":"fallback"];
    if(statusKey)$("status").textContent=WORDS[lang][statusKey]+statusExtra;
    if(installState)$("install-help").textContent=WORDS[lang][installState];
    limits();
  }
  function limits() {
    const mode=$("mode").value, cap=capabilities?.modes?.[mode];
    $("text-label").hidden=!["text","url"].includes(mode);$("file-label").hidden=["text","url"].includes(mode);
    $("camera").hidden=!["photo","scan","screenshot"].includes(mode);$("snapshot").hidden=$("camera").hidden;
    $("record").hidden=mode!=="voice_note";
    if(cap){$("limits").textContent=WORDS[lang].limits+": "+JSON.stringify(cap);$("file").accept=cap.types.join(",");}
    const unavailable=!cap||(capabilities?.unavailable_modes||[]).includes(mode);
    $("camera").disabled=unavailable;$("record").disabled=unavailable;
    $("queue").disabled=!connectionReady()||unavailable;
  }
  async function render() {
    const rows=await entries();$("outbox").replaceChildren();
    if(!rows.length){const li=document.createElement("li");li.textContent=WORDS[lang].empty;$("outbox").append(li);}
    for(const row of rows.sort((a,b)=>a.createdAt-b.createdAt)) {
      const li=document.createElement("li"), text=document.createElement("p");
      text.textContent=row.id+" · "+(row.receiptId&&!row.acquisitionId?WORDS[lang].acknowledged+" · ":"")+(WORDS[lang][row.state]||row.state)+(row.receiptId?" · "+row.receiptId:"")+(row.processingState==="attention"?" · "+WORDS[lang].attention:"")+(row.error?" · "+row.error:"");li.append(text);
      if(row.state!=="acquired")li.append(button("retry",()=>sendRow(row.id)));
      li.append(button("remove",async()=>{if(!confirm(WORDS[lang].localOnly))return;await change(row.id,()=>null);await render();}));
      if(row.acquisitionId)li.append(button("download",()=>download(row.id)));
      $("outbox").append(li);
    }
  }
  async function connect() {
    const value=await api("/session",{}, {anonymous:true});
    auth={...value,expiresAt:Date.now()+value.expires_in*1000};identity={device_id:value.device_id,instance_id:value.instance_id,channel:value.channel};
    await saveSetting("identity",identity);say("connected");limits();await render();await ownerRefresh();
  }
  async function confirmPairDestination(value) {
    const dialog=$("pair-confirm"), trigger=$("pair");
    $("pair-confirm-title").textContent=WORDS[lang].confirmPair;
    $("pair-confirm-destination").textContent=value.origin+"\n"+value.instance_id+"\n"+value.scope;
    $("pair-confirm-accept").textContent=lang==="it"?"Conferma abbinamento":"Confirm pairing";
    $("pair-confirm-cancel").textContent=lang==="it"?"Annulla":"Cancel";
    trigger.disabled=true;
    return new Promise(resolve=>{
      let settled=false;
      const finish=accepted=>{
        if(settled)return;settled=true;
        dialog.close();dialog.oncancel=null;dialog.onclose=null;
        $("pair-confirm-accept").onclick=null;$("pair-confirm-cancel").onclick=null;
        trigger.disabled=false;trigger.focus();resolve(accepted);
      };
      $("pair-confirm-accept").onclick=()=>finish(true);
      $("pair-confirm-cancel").onclick=()=>finish(false);
      dialog.oncancel=event=>{event.preventDefault();finish(false);};
      dialog.onclose=()=>finish(false);
      try{dialog.showModal();$("pair-confirm-cancel").focus();}
      catch(error){finish(false);}
    });
  }
  async function pair() {
    if(!$("retain-pairing").checked)throw new Error(WORDS[lang].retainRequired);
    const value=JSON.parse($("pair-code").value);
    if(value.origin!==location.origin||value.scope!==capabilities.scope||typeof value.instance_id!=="string"||typeof value.challenge!=="string")throw new Error(WORDS[lang].wrongDevice);
    if(!await confirmPairDestination(value))return;
    const result=await api("/pair/redeem",{challenge:value.challenge,label:$("device-label").value,instance_id:value.instance_id},{anonymous:true});
    auth={...result,channel:"paired_pwa",expiresAt:Date.now()+30*24*60*60*1000};
    await saveSetting("credential",auth);identity={device_id:auth.device_id,instance_id:auth.instance_id,channel:auth.channel};await saveSetting("identity",identity);
    $("pair-code").value="";say("paired");limits();await render();
  }
  async function enqueue(event) {
    event.preventDefault();await requireConnection();const submittingIdentity=identity;
    const mode=$("mode").value;let blob,name,capturedAt=new Date().toISOString();
    if(["text","url"].includes(mode)){blob=new Blob([$("text").value]);name="capture.txt";}
    else if(media&&media.mode===mode){blob=media.blob;name=media.name;capturedAt=media.capturedAt;}
    else {blob=$("file").files[0];name=blob?.name;}
    if(!blob||!blob.size)throw new Error(WORDS[lang].unsupported);
    const suffix=name.split(".").pop().toLowerCase(), types={txt:"text/plain",md:"text/markdown",pdf:"application/pdf",png:"image/png",jpg:"image/jpeg",jpeg:"image/jpeg",wav:"audio/wav"};
    const cap=capabilities.modes[mode], maximum=cap.maximum_bytes||({pdf:cap.maximum_pdf_bytes,png:cap.maximum_photo_bytes,jpg:cap.maximum_photo_bytes,jpeg:cap.maximum_photo_bytes,wav:cap.maximum_audio_bytes}[suffix]||cap.maximum_text_bytes);
    const mime=mode==="url"?"text/uri-list":types[suffix];
    if(!types[suffix]||!cap.types.includes(mime)||blob.size>maximum||(capabilities.unavailable_modes||[]).includes(mode))throw new Error(WORDS[lang].unsupported);
    const metadata={schema_version:1,client_submission_id:uuid(),captured_at:capturedAt,mode,channel:identity.channel,filename:name,declared_mime:mode==="url"?"text/uri-list":types[suffix]};
    for(const [id,key] of [["note","note"],["area","area_id"],["project","project_id"]]) if($(id).value)metadata[key]=$(id).value;
    const bytes=new Uint8Array(await blob.arrayBuffer()), encoded=bytes64(bytes), fp=await fingerprint(bytes,metadata);
    await requireConnection();if(identity!==submittingIdentity)throw new Error(WORDS[lang].wrongDevice);
    const row={schema_version:1,id:metadata.client_submission_id,metadata,payload_base64:encoded,byteSize:encoded.length+new TextEncoder().encode(canonical(metadata)).length+1024,
      fingerprint:fp,device_id:identity.device_id,instance_id:identity.instance_id,channel:identity.channel,state:"queued",lease:0,createdAt:Date.now(),receiptId:null,acquisitionId:null,error:null};
    await transaction("items","readwrite",(store,done)=>{const r=store.getAll();r.onsuccess=()=>{
      if(!connectionReady()||identity!==submittingIdentity){done("pairNeeded");return;}
      if(r.result.length>=MAX_ITEMS||r.result.reduce((n,v)=>n+v.byteSize,0)+row.byteSize>MAX_BYTES){done(false);return;}
      store.add(row);done(true);
    };}).then(async ok=>{if(ok==="pairNeeded")await requireConnection();if(!ok||ok!==true)throw new Error(WORDS[lang][ok==="pairNeeded"?"pairNeeded":"storage"]);});
    media=null;$("file").value="";$("text").value="";$("note").value="";say("queued");await render();await flush();
  }
  function verifyReceipt(row, receipt) {
    if(receipt.device_id!==row.device_id||receipt.metadata.client_submission_id!==row.id||receipt.fingerprint!==row.fingerprint)throw new Error(WORDS[lang].payloadChanged);
  }
  async function acknowledged(row, receipt) {
    verifyReceipt(row,receipt);
    return await change(row.id,current=>({...current,state:"acknowledged",receiptId:receipt.id,payload_base64:null,
      metadata:{client_submission_id:row.id,mode:receipt.metadata.mode,channel:row.channel,captured_at:receipt.metadata.captured_at},byteSize:1024,error:null}));
  }
  async function sendRow(id) {
    await requireConnection();
    if(!navigator.onLine){say("offline");return;}
    const leaseToken=uuid();
    const row=await change(id,current=>{if(current.lease>Date.now()||current.state==="acquired")return current;return {...current,leaseToken,lease:Date.now()+30000,state:current.receiptId?"acknowledged":"sending"};});
    if(!row||row.state==="acquired"||row.leaseToken!==leaseToken)return;
    if(row.device_id!==auth.device_id||row.instance_id!==auth.instance_id||row.channel!==auth.channel){await change(id,r=>({...r,lease:0,state:"attention",error:WORDS[lang].wrongDevice}));await render();return;}
    try {
      let found;
      try{found=await api("/submissions/"+id);}catch(error){if(error.status!==404)throw error;}
      if(found){await acknowledged(row,found.submission);}
      else {
        if(row.receiptId||!row.payload_base64)throw new Error(WORDS[lang].uncertain);
        const value=await api("/submissions",{metadata:row.metadata,payload_base64:row.payload_base64});await acknowledged(row,value.submission);
      }
      const result=found?.acquisition?{receipt:found.acquisition}:await api("/submissions/"+id+"/process",{});
      await change(id,r=>({...r,lease:0,acquisitionId:result.receipt.acquisition_id,
        state:"acquired",processingState:result.receipt.processing.status,error:result.receipt.processing.reason||null}));
      say("acquired",result.receipt.processing.status==="attention"?" · "+WORDS[lang].attention:"");
    } catch(error) {await change(id,r=>r.state==="acquired"||r.leaseToken!==leaseToken?r:({...r,lease:0,state:"attention",error:error.message||WORDS[lang].uncertain}));}
    await render();
  }
  async function flush() {if(flushActive)return;flushActive=true;try{for(const row of await entries())if(row.state!=="acquired")await sendRow(row.id);}finally{flushActive=false;}}
  async function download(id) {
    const row=(await entries()).find(r=>r.id===id);
    if(row&&(row.device_id!==auth?.device_id||row.instance_id!==auth?.instance_id))throw new Error(WORDS[lang].wrongDevice);
    const response=await fetch("/capture/submissions/"+id+"/original",{headers:headers(),credentials:"omit",cache:"no-store"});
    if(!response.ok)throw new Error(WORDS[lang].pairNeeded);
    const blob=await response.blob(), url=URL.createObjectURL(blob), anchor=document.createElement("a");
    anchor.href=url;anchor.download="capture.bin";anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function serverReceipts() {
    const result=await api("/submissions");$("server-receipts").replaceChildren();
    for(const row of result.submissions){const li=document.createElement("li");li.textContent=row.metadata.client_submission_id+" · "+row.status;$("server-receipts").append(li);}
  }
  async function ownerRefresh() {
    if(auth?.channel!=="local_browser")return;
    const value=await api("/admin/devices");$("origin").value=value.origin||"";$("devices").replaceChildren();
    for(const row of value.devices){const li=document.createElement("li");li.textContent=row.label+" · "+row.device_id+" · "+(row.revoked_at||"active");
      if(!row.revoked_at)li.append(button("revoke",async()=>{await api("/admin/revoke",{device_id:row.device_id});say("ownerDone");await ownerRefresh();}));$("devices").append(li);}
    const captures=await api("/admin/submissions");$("owner-captures").replaceChildren();
    for(const row of captures.items){const li=document.createElement("li"), p=document.createElement("p"), acquired=row.acquisition;
      p.textContent=row.submission.metadata.mode+" · "+row.submission.id+" · "+(acquired?acquired.processing.status:"submission committed; not acquired")+" · "+WORDS[lang].retained;li.append(p);
      if(acquired){const link=document.createElement("a");link.href="/documents/"+acquired.document_id;link.textContent="Knowledge / "+acquired.document_id;li.append(link);
        const label=document.createElement("label"), span=document.createElement("span"), days=document.createElement("input");span.textContent=WORDS[lang].days;days.type="number";days.min="1";days.max="365";days.value="30";label.append(span,days);li.append(label);
        const quarantined=row.quarantine?.action==="quarantine";
        li.append(button(quarantined?"undo":"quarantine",async()=>{await api("/admin/submissions/"+row.submission.id+"/quarantine",{action:quarantined?"undo":"quarantine",days:Number(days.value),request_id:uuid()});say("ownerDone");await ownerRefresh();}));
        if(row.quarantine){const q=document.createElement("p");q.textContent=row.quarantine.action+" · "+(row.quarantine.retention_until||row.quarantine.at)+" · "+WORDS[lang].retained;li.append(q);}}
      $("owner-captures").append(li);
    }
  }
  async function stopMedia() {
    $("stop").disabled=true;$("snapshot").disabled=true;
    if(recorder){const r=recorder;recorder=null;clearTimeout(r.timer);r.processor.disconnect();r.source.disconnect();await r.context.close();
      const size=r.chunks.reduce((n,v)=>n+v.length,0), buffer=new ArrayBuffer(44+size*2), view=new DataView(buffer);
      const text=(at,value)=>[...value].forEach((c,i)=>view.setUint8(at+i,c.charCodeAt(0)));
      text(0,"RIFF");view.setUint32(4,36+size*2,true);text(8,"WAVE");text(12,"fmt ");view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,r.rate,true);view.setUint32(28,r.rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,"data");view.setUint32(40,size*2,true);
      let at=44;for(const chunk of r.chunks)for(const sample of chunk){view.setInt16(at,Math.max(-32768,Math.min(32767,Math.round(sample*32767))),true);at+=2;}
      media={blob:new Blob([buffer],{type:"audio/wav"}),name:"capture.wav",mode:"voice_note",capturedAt:r.started};$("media-status").textContent=WORDS[lang].mediaReady;
    }
    if(stream){for(const track of stream.getTracks())track.stop();stream=null;}$("video").srcObject=null;$("video").hidden=true;
  }
  async function camera() {
    await stopMedia();if(!isSecureContext||!navigator.mediaDevices?.getUserMedia){$("media-status").textContent=WORDS[lang].mediaUnsupported;return;}
    try{stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"environment"},audio:false});$("video").srcObject=stream;$("video").hidden=false;await $("video").play();$("snapshot").disabled=false;$("stop").disabled=false;$("media-status").textContent=WORDS[lang].cameraActive;}
    catch(error){$("media-status").textContent=WORDS[lang].mediaDenied;await stopMedia();}
  }
  async function snapshot() {
    const video=$("video"), canvas=document.createElement("canvas");canvas.width=video.videoWidth;canvas.height=video.videoHeight;
    if(!canvas.width||canvas.width*canvas.height>20000000)throw new Error(WORDS[lang].unsupported);
    canvas.getContext("2d").drawImage(video,0,0);const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",.9));
    media={blob,name:"capture.jpg",mode:$("mode").value,capturedAt:new Date().toISOString()};await stopMedia();$("media-status").textContent=WORDS[lang].mediaReady;$("queue").focus();
  }
  async function record() {
    await stopMedia();if(!isSecureContext||!navigator.mediaDevices?.getUserMedia||!window.AudioContext){$("media-status").textContent=WORDS[lang].mediaUnsupported;return;}
    try{stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1},video:false});const context=new AudioContext();await context.resume();const source=context.createMediaStreamSource(stream), processor=context.createScriptProcessor(4096,1,1), gain=context.createGain();gain.gain.value=0;
      recorder={context,source,processor,chunks:[],rate:context.sampleRate,started:new Date().toISOString(),timer:null};const selected=recorder;
      processor.onaudioprocess=event=>{if(recorder!==selected)return;selected.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));if(selected.chunks.length*4096*2>9*1024*1024)run(stopMedia);};
      source.connect(processor);processor.connect(gain);gain.connect(context.destination);selected.timer=setTimeout(()=>run(stopMedia),90000);$("stop").disabled=false;$("media-status").textContent=WORDS[lang].micActive;
    }catch(error){$("media-status").textContent=WORDS[lang].mediaDenied;await stopMedia();}
  }
  async function scanQr() {
    if(!window.BarcodeDetector){say("qrUnavailable");return;}
    await camera();if(!stream)return;const detector=new BarcodeDetector({formats:["qr_code"]});let attempts=0;
    const scan=async()=>{if(!stream||++attempts>120){await stopMedia();return;}try{const codes=await detector.detect($("video"));if(codes.length){$("pair-code").value=codes[0].rawValue;await stopMedia();$("pair").focus();return;}}catch(error){say("qrUnavailable");await stopMedia();return;}setTimeout(scan,500);};await scan();
  }
  function showInstallation(key) {
    installState=key;$("install-help").hidden=false;$("install-help").textContent=WORDS[lang][key];
  }
  function setupInstallation() {
    window.addEventListener("beforeinstallprompt",event=>{
      event.preventDefault();if(location.protocol!=="https:"||!isSecureContext)return;
      installEvent=event;$("install").hidden=false;showInstallation("installReady");
    });
    window.addEventListener("appinstalled",()=>{
      installEvent=null;$("install").hidden=true;showInstallation("installComplete");
    });
    $("install").onclick=()=>run(async()=>{
      if(!installEvent)return;
      const event=installEvent;installEvent=null;$("install").hidden=true;
      showInstallation("installPrompt");
      await event.prompt();const choice=await event.userChoice;
      if(installState!=="installComplete")showInstallation(choice?.outcome==="accepted"?"installAccepted":"installDismissed");
    });
  }
  function connectionReady() {
    return !!(identity&&auth&&auth.expiresAt>Date.now()
      &&identity.device_id===auth.device_id&&identity.instance_id===auth.instance_id
      &&identity.channel===auth.channel
      &&(auth.channel!=="paired_pwa"||auth.origin===location.origin));
  }
  async function requireConnection() {
    if(connectionReady())return;
    await forgetPairing();limits();throw new Error(WORDS[lang].pairNeeded);
  }
  async function forgetPairing() {
    auth=null;identity=null;
    await saveSetting("credential",undefined);await saveSetting("identity",undefined);
  }
  async function restorePairing() {
    identity=await setting("identity");const saved=await setting("credential");
    if(saved?.expiresAt>Date.now()&&saved.origin===location.origin){auth=saved;}
    else if(saved||identity?.channel==="paired_pwa"){await forgetPairing();}
  }
  async function boot() {
    db=await openDB();const savedLanguage=await setting("language");if(["en","it"].includes(savedLanguage))lang=savedLanguage;$("language").value=lang;
    await restorePairing();
    capabilities=await setting("capabilities");
    try{capabilities=await api("/capabilities",undefined,{anonymous:true});await saveSetting("capabilities",capabilities);}catch(error){if(!capabilities)throw error;say("offline");}
    $("connect").hidden=capabilities.transport==="paired_pwa";$("pair-panel").hidden=capabilities.transport!=="paired_pwa";$("owner-panel").hidden=capabilities.transport!=="local_browser";
    translate();await render();
    if(location.protocol==="https:"&&isSecureContext&&"serviceWorker" in navigator){try{const registration=await navigator.serviceWorker.register("/capture/worker.js",{scope:"/capture/"});registration.update();navigator.serviceWorker.ready.then(()=>{if(!statusKey)say("installed");});}catch(error){say("installUnavailable");}}
    $("language").onchange=()=>run(async()=>{lang=$("language").value;await saveSetting("language",lang);translate();await render();});
    $("connect").onclick=()=>run(connect);$("pair").onclick=()=>run(pair);$("capture-form").onsubmit=event=>run(()=>enqueue(event));$("retry").onclick=()=>run(flush);$("receipts").onclick=()=>run(serverReceipts);
    $("mode").onchange=()=>run(async()=>{await stopMedia();media=null;$("file").value="";limits();});$("camera").onclick=()=>run(camera);$("snapshot").onclick=()=>run(snapshot);$("record").onclick=()=>run(record);$("stop").onclick=()=>run(stopMedia);$("scan-qr").onclick=()=>run(scanQr);
    $("forget").onclick=()=>run(async()=>{if(!confirm(WORDS[lang].forgetConfirm))return;await forgetPairing();limits();say("pairNeeded");});
    $("configure").onclick=()=>run(async()=>{await api("/admin/origin",{origin:$("origin").value,confirm_rebind:$("confirm-rebind").checked});$("confirm-rebind").checked=false;say("ownerDone");await ownerRefresh();});
    $("pair-qr").onclick=()=>run(async()=>{const value=await api("/admin/pair",{});if(qrUrl)URL.revokeObjectURL(qrUrl);qrUrl=URL.createObjectURL(new Blob([value.qr_svg],{type:"image/svg+xml"}));$("qr").src=qrUrl;$("qr").hidden=false;const {qr_svg,...code}=value;$("qr-text").value=JSON.stringify(code);$("qr-text").hidden=false;$("qr-status").textContent=WORDS[lang].qrExpiry+" "+value.origin+" "+value.instance_id+" "+value.scope;setTimeout(()=>{$("qr").hidden=true;$("qr-text").value="";$("qr-text").hidden=true;if(qrUrl)URL.revokeObjectURL(qrUrl);},120000);});
    $("owner-refresh").onclick=()=>run(ownerRefresh);
    window.addEventListener("online",()=>run(flush));window.addEventListener("offline",()=>say("offline"));window.addEventListener("pagehide",()=>{if(stream)for(const track of stream.getTracks())track.stop();});
    if(updates)updates.onmessage=()=>run(render);window.addEventListener("focus",()=>run(async()=>{limits();await render();}));
    setupInstallation();
    if(location.protocol==="https:"){const link=document.createElement("link");link.rel="manifest";link.href="/capture/manifest.webmanifest";document.head.append(link);}
    if(!navigator.onLine)say("offline");
  }
  document.addEventListener("DOMContentLoaded",()=>{translate();$("language").value=lang;$("language").onchange=()=>{lang=$("language").value;translate();};run(boot);});
})();

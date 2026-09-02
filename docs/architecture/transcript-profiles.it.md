# Profili transcript locali versionati

`0.9/S05` aggiunge intake locale esplicito di SRT e WebVTT dietro contratti provider-neutral.
Lectio pubblica questo percorso limitato con package, runtime e identità embedded `0.9.0` sotto il
tag `v0.9.0`.

## Matrice chiusa dei profili

| Profilo | Selettore accettato | Encoding | Grammatica timestamp | Gestione speaker |
|---|---|---|---|---|
| `srt-v1` | un file `.srt` o una cartella non ricorsiva contenente soltanto file regolari `.srt` | UTF-8 strict o UTF-8 BOM | `HH:MM:SS,mmm --> HH:MM:SS,mmm`; le ore hanno almeno due cifre | non inferito; l'assenza è esplicita |
| `webvtt-v1` | un file `.vtt` o una cartella non ricorsiva contenente soltanto file regolari `.vtt` | UTF-8 strict o UTF-8 BOM | `MM:SS.mmm` o `HH:MM:SS.mmm`, più impostazioni cue bounded | un solo `<v label>` iniziale è un'osservazione non verificata; voice tag con classi, ripetuti o malformati sono ambigui |

La matrice è chiusa e versionata nello schema. Non esiste un profilo plain-text. SRT usa la
descrizione di formato della Library of Congress insieme alla grammatica esatta qui definita; non
viene trattato come linguaggio completamente standardizzato. WebVTT usa la specifica pubblica W3C
ma accetta intenzionalmente un sottoinsieme bounded. I blocchi `STYLE` e `REGION` sono rifiutati. I
blocchi `NOTE` sono ignorati con warning sanitizzato. Metadati header come le mappe timestamp media
non vengono interpretati.

Un futuro profilo richiede una specifica pubblica stabile, fixture sintetiche riproducibili, un
contratto versionato separato e smoke permanente positivo. Profili proprietari, export provider
senza grammatica pubblica stabile, auto-detection e fallback silenzioso sono assenti.

## Ordine di autorità e confine canonico

L'adapter crea prima uno snapshot di una sola selezione esplicita. Apre ogni candidato in sola
lettura senza seguire link, acquisisce byte esatti bounded, calcola SHA-256 e ricontrolla identità
del file, dimensione e mtime prima e dopo la lettura e di nuovo dopo il parsing. Il buffer exact-byte
è autorevole; una stringa decodificata non viene mai usata per ricostruire l'Original.

Solo una transazione completa e coerente promuove la catena seguente:

1. `Original` exact-byte content-addressed;
2. `Document` provider-neutral per Source e locator opaco;
3. `DocumentVersion` per il digest esatto dei byte;
4. `Acquisition` read-only senza URL, origin, credenziale o dichiarazione derived-complete;
5. evidenza provider-neutral di revisione transcript;
6. manifest derivato, JSON cue e rappresentazione testuale legati tramite checksum.

I record canonici generici usano `application/octet-stream`. L'interpretazione di formato ed
encoding appartiene al confine derivato. Un file malformato produce un errore chiuso per item e
nessuna promozione canonica o derivata parziale. Crash o cancellazione non possono esporre output
staged come completo.

## Identità provider-neutral

| Oggetto | Input dell'identità | Esplicitamente non autorevole |
|---|---|---|
| Transcript / Document | ID interno Source più digest opaco del locator confinato alla Source | filename, percorso assoluto/relativo, titolo, ID meeting/provider, URL |
| Revisione / Version | identità transcript più SHA-256 dell'Original esatto | mtime filesystem, lingua dichiarata, ordine timestamp, ID revisione provider |
| Cue | ID revisione, ordinale, millisecondi inizio/fine e SHA-256 del testo cue | identificatore cue, speaker label, impostazioni temporali, nome partecipante |
| Original | SHA-256 e dimensione dei byte esatti | testo decodificato, newline normalizzati, output del parser |

Byte uguali e invariati vengono riprodotti senza nuova Version o Acquisition. Byte modificati creano
una nuova Version e revisione sotto lo stesso Document confinato alla Source. Byte uguali osservati
tramite una Source diversa hanno identità transcript e Document diverse; può essere riutilizzato
soltanto l'Original exact-byte globale. Il ritorno a un digest già conservato segue il contratto
Version per contenuto esatto esistente e non crea equivalenza semantica.

Filename, percorso, titolo, meeting ID, cue ID, speaker label, partecipante dichiarato, lingua,
timestamp, URL e identificatore provider sono soltanto osservazioni. S05 non attesta l'esistenza di
audio, video, riunione o partecipante. Non risolve una speaker label in una persona. Non esistono
merge o associazioni implicite con email locale, Gmail, Drive o qualsiasi altra Source.

## Parser sostituibile e provenance della derivazione

Il primo parser è `provelume.bounded-transcript` 1.0.0 dietro parser protocol 1. Un parser espone ID,
versione, protocollo e ID dei profili supportati. La provenance restituita deve corrispondere
esattamente all'implementazione selezionata, altrimenti l'intake fallisce closed.

Parser, profilo, formato, adapter e osservazioni filesystem sono esclusi dal record di revisione
provider-neutral. Sono conservati in
`state/transcript-intake/recipes/<revision>/<derivation>.json`, con:

- legami interni Original, transcript, revisione, Source e connector;
- profilo e formato interpretato;
- ID/versione/protocollo di adapter e parser;
- fingerprint esatto delle impostazioni e tutti i limiti effettivi;
- checksum opachi di locator e identità filesystem, più mtime osservato;
- dichiarazioni esplicite no-network, no-download, no-fallback e no-active-content.

La derivation key è l'hash di checksum Original, profilo, identità/versione/protocollo parser e
impostazioni. Un parser sostitutivo crea quindi una nuova recipe e un nuovo artifact derivato senza
creare una nuova Version o Acquisition canonica quando i byte sono invariati. Possono essere
conservate più recipe; viene esposto l'artifact completo valido più recente. Il rebuild usa la
recipe più recente conservata e richiede il suo parser esatto. Versioni parser mancanti falliscono
visibilmente invece di sostituire silenziosamente il parser corrente.

Il `transcript_bundle` schema 1 registra la stessa provenance e i checksum di `cues.json` e
`transcript.txt`. I byte cue e testo sono verificati prima dell'ispezione. La rimozione elimina solo
file derivati transcript, record artifact ed edge di provenance derivata; conserva byte Original,
record canonici e recipe.

Gli schema inclusi nel package sono:

- `transcript_contract.schema.json` — configurazione Source esplicita;
- `transcript_revision.schema.json` — evidenza revisione senza parser/formato;
- `transcript_recipe.schema.json` — derivazione riproducibile e versionata;
- `transcript_bundle.schema.json` — manifest completo;
- `transcript_cues.schema.json` — rappresentazione cue inerte.

## Encoding e normalizzazione del testo

Sono accettati soltanto UTF-8 strict e UTF-8 con un solo BOM iniziale. UTF-16, encoding locale,
UTF-8 invalido e NUL falliscono con `transcript_encoding_unsupported`; non esiste fallback con
replacement character o rilevamento encoding. Byte e checksum dell'Original non cambiano mai.

Rimozione del BOM e conversione CRLF/CR in LF avvengono soltanto nel parsing derivato. Il manifest
registra presenza BOM e stile di fine riga sorgente come `none`, `lf`, `crlf`, `cr` o `mixed`. La
normalizzazione emette warning chiusi. L'output testuale unisce deterministicamente il testo dei cue
con due byte LF e non dichiara mai di essere un Original.

## Anomalie deterministiche

Intervalli invalidi, nulli o negativi, sintassi timestamp invalida, durata/timeline eccessive, testo
cue mancante e struttura malformata sono errori. Le condizioni seguenti sono warning deterministici:

| Condizione | Codice | Effetto |
|---|---|---|
| identificatore cue ripetuto | `cue_identifier_duplicate` | cue conservato; l'identificatore resta osservazione |
| stesso intervallo e digest testo | `cue_duplicate` | cue conservato; nessuna dedup semantica |
| intervallo che interseca qualsiasi cue precedente | `cue_overlap` | cue conservato; overlap visibile |
| inizio precedente a qualsiasi inizio già visto | `cue_out_of_order` | ordine input conservato |
| voice tag malformato/ripetuto/con classe | `speaker_label_ambiguous` | nessuna speaker label promossa |
| nessuna speaker label accettata nel file | `speaker_label_absent` | assenza esplicita |
| BOM UTF-8 | `utf8_bom_removed` | la decodifica derivata omette il BOM |
| righe sorgente CRLF/CR | `line_endings_normalised` | il testo derivato usa LF |
| blocco NOTE WebVTT | `webvtt_note_ignored` | il contenuto del blocco non è rappresentato |

I warning sono chiusi, ordinati e bounded. Profilo/estensione non supportati, formato ambiguo,
encoding non supportato e input malformato falliscono visibilmente; nessun input viene riprovato con
un altro profilo.

## Lifecycle esplicito di Source e capability

Ogni configurazione percorso/profilo/selezione è un ConnectorInstance e una Source. La creazione è
disabilitata e manuale per default ed esegue soltanto validazione: non avvia scan, parsing, job,
watcher o richiesta di rete. La definizione connector dichiara `network_access: none`; l'istanza ha
`network_mode: disabled`, nessun origin consentito, scope, autorizzazione o secret reference.

L'operatore sceglie separatamente:

- file o cartella esatti e `srt-v1` o `webvtt-v1`;
- enable, pause o disable;
- schedule manuale o intervallo bounded;
- refresh/import, run, retry o cancellation;
- reset cursore/resync;
- riconfigurazione solo quando disabilitata;
- rimozione tombstone della Source;
- rimozione o rebuild della rappresentazione derivata.

Le cartelle sono a un solo livello. Ogni entry osservata conta nel limite di enumerazione; directory
nested, link, reparse point, file hard-linked o speciali ed estensioni errate fanno fallire lo
snapshot. I selettori UNC noti sono rifiutati. Non esistono discovery ricorsiva, ricerca globale,
watcher, backfill nascosto o scrittura source-side. L'adapter non modifica, rinomina o cancella mai
un file sorgente.

## Esecuzione durevole e bounded

`transcript.intake` è un job Vigilia confinato alla Source. L'identità della richiesta lega
Source/revisione config, checksum snapshot della selezione, profilo, identità parser/adapter/
impostazioni e limiti. I record durevoli request, work, run e cursor omettono percorsi, filename,
titoli, testo transcript e speaker label. Lo stato per item contiene soltanto ID/checksum interni,
valori dimensione/conteggio, stato ed errori chiusi.

Snapshot, work journal e cursore Source restano confinati a una sola Source. Batch/backfill si
arrestano ai limiti di file, enumerazione, lettura totale, spazio temporaneo e durata. Il retry
scheduler è limitato a tre tentativi con backoff bounded da 30 a 300 secondi. I checkpoint avanzano
dopo ogni item terminale. La cancellazione è controllata tra gli item e le deadline bounded di
lettura/parser limitano l'item corrente. Lease scaduti con progresso sono resumable; item già
committati vengono riprodotti come skip. Un reset cursore azzera solo quella Source e imposta resync
esplicito richiesto.

Una selezione cambiata dopo la coda o una mutazione file durante lettura o parsing produce
`transcript_input_changed`, non promuove nuovo stato e segue retry bounded. Gli errori formato per
item restano visibili in `completed_with_errors`; il checkpoint Source resta incompleto con
`resync_required=true`. Il recovery della transazione atomica non dichiara mai completo un manifest
parziale.

## Limiti chiusi

| Limite | Default | Massimo contrattuale |
|---|---:|---:|
| byte per file | 32 MiB | 256 MiB |
| file per job | 500 | 10.000 |
| entry enumerate | 2.000 | 50.000 |
| byte letti totali | 256 MiB | 4 GiB |
| cue per file | 10.000 | 100.000 |
| caratteri per riga | 16 KiB | 1 MiB |
| caratteri per cue | 64 KiB | 5 MiB |
| caratteri decodificati per file | 2.000.000 | 50.000.000 |
| durata cue | 24 ore | 7 giorni |
| fine timeline | 30 giorni | 365 giorni |
| warning per file | 500 | 10.000 |
| errori item per job | 500 | 10.000 |
| byte temporanei per job | 512 MiB | 8 GiB |
| byte derivati per file | 32 MiB | 256 MiB |
| secondi per file | 30 | 300 |
| secondi per job | 600 | 86.400 |

I record limite sono completi e rifiutano campi sconosciuti o mancanti. La lettura totale non può
essere inferiore alla dimensione file; l'enumerazione non può essere inferiore al numero file; lo
spazio temporaneo non può essere inferiore alla dimensione file; la durata job non può essere
inferiore alla durata per file. La dimensione output è misurata dopo serializzazione JSON/testo,
impedendo all'amplificazione degli escape di aggirare il limite derived-output.

## Confine contenuto inerte e privacy

Testo transcript, impostazioni e identificatori cue non vengono mai eseguiti o interpretati come
HTML, JavaScript, escape terminale, percorso file o URL. Il parser non segue link, non carica
risorse o contenuti incorporati, non valuta template, non esegue shell/processi e non associa media.
Il Browser usa autoescaping server-side e rende il testo sorgente in blocchi `pre` inerti. Content
Security Policy e controlli loopback restano invariati.

Log, ricevute scheduler, checkpoint ed export operativi non contengono testo transcript, nome
speaker, titolo privato, filename/percorso, identificatore provider, URL, credenziale, token o secret
risolto. Espongono ID interni, SHA-256, conteggi, codici chiusi di stato/errore/warning e timing
scheduler bounded. L'API read-only redige percorsi configurati e nomi Source; il contenuto viene
restituito soltanto da un'ispezione esplicita della revisione o lettura exact-Original.

Non vengono aggiunti credenziali, SDK provider, modelli, codec, payload nativi o fixture private. Le
fixture sintetiche usano label inventate e URL `.invalid`. L'esecuzione locale non crea socket,
download runtime o fallback remoto. La configurazione Source rifiuta selettori di rete noti;
comportamento di altri filesystem montati/network dell'OS resta fuori dalla matrice qualificata e
non può essere dichiarato Source locale qualificata no-network.

## CLI, service, API e Browser

L'application service possiede tutte le mutazioni. La famiglia CLI `transcript-*` espone
capability, create/list/show/state/configure/schedule/remove della Source, checkpoint/resync,
queue/run/job/retry/cancel, ispezione revisione/Original e remove/rebuild derivato.

L'API è read-only:

- `GET /api/v1/transcripts/capability`;
- `GET /api/v1/transcripts/sources` e `/sources/{source_id}`;
- `GET /api/v1/transcripts/sources/{source_id}/checkpoint`;
- `GET /api/v1/transcripts/jobs` e `/jobs/{job_id}`;
- `GET /api/v1/transcripts/revisions` e `/revisions/{revision_id}`;
- `GET /api/v1/transcripts/revisions/{revision_id}/original`.

Il contenuto revisione è opt-in con `include_content=true`; liste e summary non contengono testo
sorgente. L'endpoint Original verifica checksum e dimensione e restituisce byte opachi. Non esiste
endpoint upload, intake remoto, `POST`, `PATCH` o `DELETE`.

`/transcripts` offre stato e controlli semanticamente equivalenti in inglese e italiano. Le
mutazioni richiedono client loopback, content type form, dimensione/campi bounded e token CSRF per
processo. Le viste non-loopback omettono percorsi e form. Label, campi e controlli restano
accessibili da tastiera e screen reader.

## Backup, trasferimento portabile e validazione

Backup/restore verificato include record canonici, Original esatti, stato durevole Source/job,
recipe e stato derivato. Export/import portabile conserva isolamento Source e legami exact-byte. La
validazione deep controlla catena revisione neutrale, identità/impostazioni recipe, checksum
manifest/rappresentazione, confinamento Source, flag no-active/no-network e chiavi privacy dello
stato operativo. Legami mancanti o corrotti falliscono visibilmente.

## Conformance e qualificazione

Conformance, evidenza piattaforma e qualificazione provider reale sono claim diversi:

| Livello | Evidenza | Claim consentito |
|---|---|---|
| conformance deterministica profilo | fixture sintetiche SRT/WebVTT valide/ostili e suite completa unit/integration | comportamento parser solo per profilo/contratto esatti |
| smoke permanente piattaforma | `.github/workflows/transcript-smoke.yml` sull'head candidate invariato | qualificazione locale SRT/WebVTT soltanto per righe OS/architettura/CPython positive |
| preview piattaforma | comportamento locale Browser/CLI/API fuori da una riga permanente positiva | preview, non qualificazione |
| qualificazione provider reale | non esiste matrice provider autenticata permanente | `false`; nessun claim cloud/provider |

La matrice target permanente è Ubuntu 24.04 x86-64 e Windows Server 2025 x86-64, entrambi con
CPython 3.12, per `srt-v1` e `webvtt-v1`. Il manifest definisce il target; un commit diventa
qualificato soltanto dopo entrambi i job exact-head positivi. macOS, ARM, altre versioni Python,
encoding non UTF-8, plain text, profili proprietari, import cloud ed export provider restano non
qualificati.

Lo smoke nega entry point socket/DNS Python e prova Original exact-byte, entrambi i parser, stringhe
ostili inerti, mapping provider-neutral e validazione deep usando soltanto dati sintetici. Non è uno
smoke provider autenticato e non qualifica audio, video, meeting o persone.

## Esclusioni esplicite

S05 non aggiunge intake audio/video, speech-to-text, ASR, Whisper, diarizzazione, download modelli,
associazione media automatica, import Plaud/Zoom/Teams/Meet, Calendar, invio email, write-back
Gmail/Drive, qualificazione cross-Source, flusso correzioni umane, Action Center, AI/RAG, sintesi,
classificazione, estrazione claim/decision/task, cloud OCR o provider AI. S06 resta lavoro successivo
per qualificazione/correzioni cross-source. S07 shell Windows/UX installer e porta `44851` restano
invariati.

Vedi [ADR 0018](../adr/0018-versioned-transcript-profiles.md), il
[contratto inglese](transcript-profiles.md) e la [guida API](../api.md).

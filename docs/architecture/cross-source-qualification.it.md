# Qualificazione cross-source e finding di correzione

`0.9/S06` è pubblicato con Lectio. Confronta Source esistenti selezionate esplicitamente e produce
finding da revisionare; non le fonde, verifica o riscrive. Le identità package, runtime ed embedded
sono `0.9.0`. Non esiste merge automatico.

## Confine di autorità e identità

Ogni ConnectorInstance e Source resta autorevole solo per la propria selezione. Cursori provider e
filesystem, page fingerprint, enumerazione, deduplica, retry, lease e resync non passano mai tra
Source. Un job di qualificazione ha un checkpoint separato per Source e legge solo record interni
conservati e rappresentazioni locali legate al checksum. Non esegue intake e non apre la rete.

I byte degli `Original` e i `DocumentVersion` esistenti restano immutabili. Byte uguali in due
Source possono riusare l'Original content-addressed già previsto dal Core, ma Document, Version,
Acquisition e provenienza Source restano separati. Metadati uguali, speaker label, componenti di un
indirizzo, timestamp o revisione provider non diventano identità globale.

## Matrice chiusa di qualificazione

La matrice schema 1 è versione `2026-09-01.1`.

| Profilo | Claim locale deterministico | Preview piattaforma | Claim reale autenticato |
|---|---|---|---|
| `filesystem-document-v1` | qualificato per legami canonici/Original | Ubuntu 24.04, Windows Server 2025 x86-64 | non applicabile |
| `ocr-document-bundle-v1` | qualificato per bundle conservati e legati al checksum | Ubuntu 24.04 x86-64 | non applicabile; l'OCR reale resta nell'evidenza S02 |
| `local-email-v1` | qualificato per record EML/Maildir chiusi | EML Ubuntu/Windows; Maildir Ubuntu | non applicabile |
| `gmail-synthetic-v1` | synthetic-qualified | Ubuntu/Windows | **unqualified** |
| `drive-synthetic-v1` | synthetic-qualified | Ubuntu/Windows | **unqualified** |
| `transcript-srt-v1` | qualificato per il profilo chiuso S05 | Ubuntu/Windows | non applicabile |
| `transcript-webvtt-v1` | qualificato per il profilo chiuso S05 | Ubuntu/Windows | non applicabile |

Le fixture sintetiche non provano il comportamento autenticato del provider. Source non elencate,
versioni algoritmo miste, rappresentazioni mancanti e combinazioni fuori dalle condizioni indicate
restano non qualificate e producono evidenza visibile, non un claim più forte.

## Schema dei finding e stati epistemici

`qualification_finding.schema.json` definisce un finding derivato immutabile. L'ID stabile hash-a
tipo/versione, Source e riferimenti interni, evidenza sanitizzata, regola e algoritmo. Il record
include:

- tipo e versione chiusi;
- ID Source e riferimenti esatti ID/fingerprint agli oggetti;
- evidenza limitata a codici, SHA-256, conteggi, dimensioni ed enum sanitizzati;
- ID/versione di regola deterministica e algoritmo;
- stato `deterministic-observation`, `possible`, `incompatible`,
  `requires-human-review` o `unqualified`;
- confidenza bounded che esplicita sempre il proprio limite;
- workflow, provenienza job/snapshot Source, timestamp operativo e limiti effettivi.

I tipi chiusi sono `possible-exact-byte-duplicate`, `possible-revision-relation`,
`observed-metadata-inconsistent`, `checksum-provenance-incompatible`, `timestamp-inconsistent`,
`language-format-discordant`, `possible-same-event-document-content`,
`possible-participant-homonym`, `representation-missing`, `representation-obsolete`,
`representation-not-reconstructible`, `representation-recipe-inconsistent` e
`qualification-required`.

La regola exact-byte è deterministica solo sui byte. Revisioni/contenuto/evento e partecipanti sono
candidati, mai relazioni o persone verificate. Componenti degli indirizzi e label transcript sono
normalizzati solo in memoria; al finding arriva esclusivamente uno SHA-256. Testo, subject, titolo,
nome, path, speaker label e ID provider non entrano nello stato operativo.

## Schema di decisioni e correzioni

`qualification_decision.schema.json` definisce l'overlay umano append-only. Una decisione lega il
finding, revisione monotona, azione, stato risultante, autore opaco, motivazione sanitizzata,
payload specifico, provenienza Source/job e timestamp. Dichiara che Original, oggetti provider e
osservazioni Source non sono cambiati e che non c'è propagazione automatica.

| Azione | Risultato | Payload e significato |
|---|---|---|
| `acknowledge` | `acknowledged` | revisionato senza conclusione |
| `accept` / `reject` | `accepted` / `rejected` | conferma o respinge solo questo finding |
| `defer` | `deferred` | osservazione bounded della data di riesame |
| `declare-distinct` | `accepted` | mantiene distinti due o più oggetti citati |
| `add-relation` | `accepted` | aggiunge `related`, `revision-of` o `distinct-from`; nessun merge |
| `correct-observation` | `accepted` | sovrappone un campo derivato chiuso |
| `supersede` | `superseded` | sostituisce una decisione precedente citata |
| `withdraw` / `revert` | `withdrawn` / `reverted` | neutralizza senza cancellare la storia |

Le motivazioni rifiutano controlli, valori simili a script/data/file/HTTP e prefissi da formula.
I valori corretti usano una grammatica inerte ancora più stretta. Una revisione attesa stale
rifiuta invii doppi o concorrenti. Source, Version, rappresentazione o fingerprint cambiati
falliscono come `qualification_reference_stale` prima dell'append. Il rebuild modifica solo viste
derivate e conserva tutta la storia.

## Job durevoli, limiti ed errori

L'identità della coda lega insieme Source ordinate, snapshot esatto, algoritmo e limiti completi.
Il risultato è preparato in una directory privata e rinominato atomicamente solo dopo il recheck di
tutti gli input. Cancellazione, eccezione o input cambiato non lasciano un risultato completo. Lease
scadute rientrano nel retry bounded; l'esaurimento fallisce visibilmente. Il resync incrementa solo
il cursore di qualificazione di quella Source. Replay identico restituisce lo stesso job; un nuovo
risultato completo supersede gli ID obsoleti senza cancellarne le decisioni.

I default sono 16 Source, 10.000 oggetti, 10.000 finding, 50.000 relazioni candidate, batch 500,
600 secondi, 512 MiB temporanei, 4 KiB per evidenza, 32 MiB di output, 1.000 caratteri di
motivazione, lease 120 secondi e tre tentativi. Ogni valore ha un ceiling chiuso; record incompleti
o con chiavi ignote falliscono. Conteggio delle coppie e dimensione serializzata impediscono output
amplification.

Gli errori chiusi includono cancellazione, conflitto, input cambiato, decisione/Source non valida,
lease scaduta, limiti/output superati, oggetto assente, riferimento stale e retry esaurito. I job
mostrano stato, tentativo, checkpoint, conteggi, codice sanitizzato e presenza/scadenza lease; il
token casuale resta interno.

## Superfici, sicurezza e recovery

Service e CLI espongono matrice/limiti, checkpoint/resync Source, queue/run/cancel/retry/rebuild,
filtri, evidenza/provenienza e decisioni/storia. Il Browser loopback EN/IT protetto usa CSRF, limiti
di encoding/body/campi, controlli nativi da tastiera, intestazioni tabella, fieldset, label,
status/alert e pannelli distinti per osservazione, evidenza, decisione e confine canonico.

La famiglia Knowledge API `/api/v1/qualification` è solo di ispezione: matrice, limiti, checkpoint
Source, job, finding, evidenza e provenienza sanitizzate, cronologia. Non ha `POST`, `PATCH`,
`DELETE`, upload o intake remoto.

Markup, formule, link, escape e payload simili a script restano dati inerti. Non esistono chiamate
SDK/provider, risoluzione credenziali, runtime download, remote fallback, AI o shell/processo. Path
controllati dalla Source non vengono dereferenziati fuori dall'Instance; riferimenti non sicuri,
mancanti o con checksum errato diventano finding o falliscono la validazione.

Backup/restore ed export/import portabile conservano job, risultati completi, checkpoint e
decisioni canoniche. La policy portabile `rebuild` riguarda indici/library e non elimina questa
evidenza durevole. Il ricalcolo dei finding resta un job esplicito. Il crash recovery non presenta
staging o decisioni parziali come complete.

# Identità e intake email locale

Stato: implementato per `0.9/S03`, attivo ma non pubblicato, tramite
[#143](https://github.com/gabned/provelume/issues/143) e owner PR `OWNER_PR_TBD`.
Package, identità incorporata, tag e release pubblicata restano `0.8.0 — Vigilia`.

La qualifica è vincolata all'owner head invariato dallo smoke permanente EML/Maildir e dai workflow
richiesti. È una qualifica locale di sviluppo, non una dichiarazione di supporto pubblicata per
`0.9.0`.

## Che cosa realizza questo slice

S03 importa evidenze email da un file EML locale selezionato esplicitamente o da un profilo Maildir
limitato. È provider-neutral, offline e disabilitato per impostazione predefinita. Non scopre
applicazioni di posta, account, cartelle o credenziali e non contatta Gmail, server IMAP/POP o altri
provider.

I seam pubblici mantengono sostituibili configurazione Source, enumerazione del contenitore,
lettura limitata dei byte esatti, parsing MIME, identità/deduplicazione, selezione del body,
estrazione degli allegati, persistenza, thread osservato e orchestrazione durevole. Il primo parser
è `email.parser.BytesParser(policy=policy.default)` di CPython 3.12, esposto come
`python.email` / `stdlib-3.12` dietro il protocollo parser 1. L'adapter Source è
`provelume.local-email` 1.0.0 dietro il protocollo adapter 1.

Il parser applica intenzionalmente un profilo più ristretto di tutto ciò che MIME può esprimere. I
byte raw esatti vengono sottoposti a hash e conservati prima di considerare un risultato di parsing.
Gli oggetti `email` di Python non diventano mai record canonici e la loro serializzazione non viene
mai usata per ricostruire l'Original.

Le fonti primarie sono la documentazione Python 3.12 di
[`email.parser`](https://docs.python.org/3.12/library/email.parser.html),
[`email.policy`](https://docs.python.org/3.12/library/email.policy.html) e
[`mailbox`](https://docs.python.org/3.12/library/mailbox.html), oltre a
[RFC 5322](https://www.rfc-editor.org/rfc/rfc5322),
[RFC 2045](https://www.rfc-editor.org/rfc/rfc2045),
[RFC 2046](https://www.rfc-editor.org/rfc/rfc2046),
[RFC 2047](https://www.rfc-editor.org/rfc/rfc2047) e
[RFC 2231](https://www.rfc-editor.org/rfc/rfc2231), oltre a
[RFC 6532](https://www.rfc-editor.org/rfc/rfc6532) per gli header internazionalizzati. Gli standard
descrivono la sintassi: non rendono affidabili un'identità, un timestamp, un media type o un nome
file dichiarati.

## Lifecycle esplicito della Source

Una Source email richiede sempre un percorso scelto dall'operatore e un profilo esplicito:

- `eml-file-v1` — esattamente un file locale regolare;
- `maildir-cur-new-v1` — esattamente una root Maildir locale con `tmp/`, `new/` e `cur/`;
- `mbox` — non supportato e rifiutato con una motivazione chiusa.

La creazione non esegue intake e registra la Source come `disabled`, con esecuzione manuale.
`enabled`, `paused` e `disabled` sono stati distinti. Abilitazione, Run now, pausa,
disabilitazione, cancellazione, rimozione ed eventuale pianificazione sono azioni locali separate.
La sola esistenza di un percorso non può avviare un job. Non vengono installati watcher, daemon,
attività di avvio o agent in background.

Le mutazioni appartengono al service locale, alla CLI e al Browser loopback protetto da CSRF.
L'API HTTP versionata è read-only e non può caricare byte EML, configurare un percorso o avviare
l'intake. La CLI e la vista di configurazione Browser locali possono mostrare il percorso scelto
dall'operatore dopo escaping; API, receipt dei job e operation record non lo espongono mai.

La rimozione di una Source conserva il tombstone e tutte le precedenti relazioni Source,
Acquisition, Document, Version, Original e provenienza. Non cancella né riscrive conoscenza già
acquisita.

## Matrice di formato e piattaforma

Lo smoke permanente usa il parser reale selezionato e messaggi sintetici generati sui seguenti
target esatti qualificati:

| Profilo | Ubuntu 24.04 x86-64 / CPython 3.12 | Windows x86-64 / CPython 3.12 | Altri target |
| --- | --- | --- | --- |
| `eml-file-v1` | qualificato | qualificato | non qualificato |
| `maildir-cur-new-v1` | qualificato | non qualificato | non qualificato |
| `mbox` | non supportato | non supportato | non supportato |

Il profilo Maildir enumera soltanto file regolari immediati in `new/` e `cur/`, in ordine
deterministico. Non legge mai `tmp/`, non cambia flag, non sposta messaggi, non pulisce file
temporanei e non attraversa cartelle annidate. Su Windows la nomenclatura standard di `cur` e il
comportamento del filesystem non sono dichiarati portabili; la capability resta quindi non
disponibile anche se CPython espone il modulo `mailbox`.

`mailbox` è stato valutato ma non è selezionato per lettura o delimitazione. Le sue astrazioni di
contenitore non stabiliscono le evidenze Provelume per byte sorgente esatti, snapshot, link e
locator. Provelume apre invece il file regolare selezionato in modalità binaria, limita la lettura,
calcola l'hash e confronta le evidenze di handle/percorso prima e dopo. CRLF, LF o line ending misti
restano byte Original esatti; soltanto un body derivato può normalizzare i line ending testuali.

Root della Source, directory richieste e messaggi candidati devono rispettare la policy no-link
della piattaforma. Sono rifiutati symlink e hardlink POSIX e, su Windows, symlink, hardlink,
junction o altri reparse point. Sono rifiutati i file non regolari. Un file che scompare, viene
rinominato o sostituito, oppure cambia evidenza rilevante di dimensione/tempo/identità durante la
lettura limitata, non viene promosso come successo. È un confine fail-closed per mutazioni
cooperative, non un sandbox del sistema operativo.

## Massimali effettivi

La configurazione può ridurre, ma non aumentare, questi massimali dello schema 1. I contatori sono
cumulativi dove indicato; capability response e ricetta di ogni job registrano i valori effettivi.

| Limite | Massimale |
| --- | ---: |
| un file EML/messaggio | 32 MiB |
| snapshot di un contenitore mailbox | 512 MiB |
| messaggi in un run | 500 |
| byte sorgente letti in un run | 256 MiB |
| campi header in un messaggio | 512 |
| blocco header completo | 256 KiB |
| singola riga header/sorgente | 16 KiB |
| parti MIME in un messaggio | 256 |
| profondità MIME | 16 |
| profondità `message/rfc822` annidata | 4 |
| allegati accettati in un messaggio | 100 |
| singolo allegato accettato | 20 MiB |
| byte allegati accettati in un messaggio | 30 MiB |
| output transfer-decoded in un messaggio | 32 MiB |
| output transfer-decoded in un run | 256 MiB |
| caratteri del body derivato | 500.000 |
| riferimenti thread conservati | 100 |
| warning conservati in un messaggio | 200 |
| errori conservati in un job | 500 |
| spazio temporaneo in un job | 512 MiB |
| tempo per messaggio | 30 secondi |
| tempo per job | 600 secondi |

Il massimale del contenitore (512 MiB) e quello di lettura del run (256 MiB) sono controlli
indipendenti. Per un singolo run prevale il controllo effettivo più basso: superarne uno fallisce in
modo chiuso e S03 non presenta uno snapshot parziale o una continuazione silenziosa come mailbox
completa.

## Identità del messaggio e deduplicazione

S03 mantiene separati:

- ID Source e versione adapter/protocollo;
- profilo del contenitore e fingerprint dello snapshot osservato;
- digest opaco del locator e identità locale del file, quando disponibile;
- SHA-256 e byte count esatti del messaggio;
- contratto, parser, impostazioni e limiti effettivi;
- osservazioni dichiarate `Message-ID`, `References` e `In-Reply-To`.

All'interno della stessa Source, l'identità esatta del contenuto possiede il Document/Version
stabile del messaggio. Reimportare la stessa osservazione e gli stessi byte è un replay e non crea
Acquisition, Document, Version, Original, allegato o provenienza duplicati. Byte uguali sotto un
altro locator riusano la stessa evidenza del messaggio nella Source, conservando la nuova
osservazione. Byte uguali in un'altra Source restano un'altra osservazione Source-scoped; S03 non
fonde Source differenti: messaggio, Document e acquisizione restano separati. Lo store globale
content-addressed può riusare in sicurezza lo stesso blob Original immutabile per digest; questa è
deduplicazione dello storage, non equivalenza d'identità cross-Source.

Un `Message-ID` apparentemente valido non è da solo una chiave d'identità. Due sequenze di byte
diverse con lo stesso ID sono entrambe conservate e ricevono un warning esplicito di collisione.
Un ID assente, malformato o ripetuto non rende non importabili byte altrimenti validi e limitati.

Anche l'identità del thread è un raggruppamento osservato e limitato alla Source. La
rappresentazione registra quali evidenze `References`/`In-Reply-To` lo hanno prodotto. Target
mancanti, ID duplicati, cicli, catene eccessive e riferimenti cross-Source non creano equivalenza.
L'eventuale qualifica cross-source appartiene a S06.

La data dichiarata nell'header, il tempo osservato nel filesystem/contenitore e il tempo di
acquisizione restano tre campi diversi. Nessuno sostituisce silenziosamente un altro.

## Original, allegati e rappresentazione derivata

Il messaggio esatto è un Original immutabile e content-addressed. Ogni allegato o parte inline
accettata viene decodificata separatamente entro il budget transfer e salvata come Original figlio
immutabile, con provenienza verso messaggio e identità esatta della parte MIME. Il nome file
dichiarato è soltanto un'osservazione. Lo storage usa un identificatore interno deterministico, mai
il nome MIME: percorsi assoluti, traversal, nomi dispositivo Windows, Unicode ambiguo e collisioni
non possono scegliere un percorso di storage.

L'`email_message_bundle` schema 1 è una rappresentazione derivata rimovibile e ricostruibile.
Contiene o collega:

- identità Source/contenitore/messaggio e digest dell'Original esatto;
- campi envelope raw/analizzati selezionati, stato defect e warning;
- timestamp dichiarati, osservati e di acquisizione separati;
- body testuale selezionato, regola, numero caratteri e digest;
- albero MIME limitato;
- identità e digest degli allegati, media/disposition/`Content-ID` dichiarati e relazione;
- evidenza reply/reference dichiarata e thread osservato con motivazione;
- parser, adapter, piattaforma, impostazioni e limiti effettivi;
- ID del job e stato immutabile dell'unità `message-complete` (il journal durevole resta autorevole
  per lo stato complessivo del job multi-messaggio);
- checksum necessari per verificare rimozione o ricostruzione complete.

Il bundle viene promosso atomicamente soltanto quando Original del messaggio, tutti gli Original
degli allegati accettati, record canonici e manifest derivato completo concordano. Body, albero
MIME, thread o indice allegati in staging/parziali non sono leggibili come successo. Rimuovere o
ricostruire il bundle non modifica Original o conoscenza canonica.

## Sicurezza MIME e contenuto attivo

Numero/byte degli header e lunghezza delle righe vengono verificati prima di consegnare il
messaggio al parser MIME. Il percorso limitato gestisce poi header assenti, ripetuti, malformati e
encoded-word; liste e gruppi di indirizzi restano osservazioni sintattiche e non diventano contatti
risolti.

`multipart/mixed`, `multipart/alternative` e `multipart/related` sono attraversati soltanto nei
budget chiusi di parti/profondità. È preferita una parte `text/plain` accettabile. La baseline S03
non ha fallback HTML-to-text: l'HTML resta soltanto nell'Original esatto del messaggio e il body
derivato è esplicitamente non disponibile. Nessun percorso email renderizza HTML, esegue script,
applica CSS remoto, invia form, segue URL, carica immagini remote o risolve riferimenti `cid:`.

Le forme transfer `7bit`, `8bit`, `binary`, Base64 e quoted-printable sono accettate soltanto dopo
controlli rigorosi di sintassi/output e nei budget cumulativi. Encoding sconosciuti e output
invalido, troncato o eccessivo falliscono in modo chiuso. La decodifica del body è qualificata solo
per dichiarazioni US-ASCII/ASCII, UTF-8, ISO-8859-1/Latin-1 e Windows-1252/CP1252. Charset
sconosciuti o invalidi mantengono un warning esplicito e lo stato body non disponibile, senza
correzioni semantiche inventate. `message/rfc822` ha un limite separato. Gli archivi sono conservati
come allegati, ma mai espansi. Parti firmate, cifrate o non supportate vengono preservate senza
dichiarare verifica di firma, mittente o cifratura.

Nessuna operazione email esegue allegati, macro, JavaScript o comandi shell. Non effettua malware
scanning né dichiara verifiche DKIM, SPF, DMARC, PGP, S/MIME o autenticità legale.

## Job durevole, retry e recupero

L'intake email usa il journal durevole di Vigilia con idempotency key legata a Source,
osservazione contenitore/messaggio, hash esatto, contratto/adapter/parser e impostazioni effettive.
Conserva checkpoint a livello messaggio e allegato accettato, lease esclusiva, heartbeat,
tentativi limitati e cancellazione cooperativa tra unità limitate.

Una lease scaduta o un crash riparte soltanto da un checkpoint committed verificato. Il replay non
può sovrascrivere un Original o duplicare Version, allegati o archi di provenienza. Un messaggio
errato viene isolato; quelli validi proseguono e lo stato complessivo diventa
`completed_with_errors` quando necessario. Prima della promozione l'adapter ricontrolla lo snapshot
della Source: una mailbox cambiata non può pubblicare un successo stale.

Warning, errori e receipt usano ID opachi, conteggi e codici chiusi. Non contengono subject, body,
indirizzi, nomi file, percorsi fisici o testo del chiamante.

La deep validation verifica binding Source/configurazione, evidenze canoniche di messaggi/allegati,
riferimenti agli Original esatti e checksum dei bundle completi senza rileggere la mailbox.
Backup/restore conserva configurazione locale, tombstone, evidenza canonica e stato durevole dei
job. L'export portabile conserva sempre l'evidenza email canonica e applica la policy scelta allo
stato derivato; un import senza bundle può ricostruirli dagli Original dei messaggi conservati. Un
percorso ripristinato assente o non qualificato lascia la Source visibilmente indisponibile e non
riscrive le acquisizioni precedenti.

## Controlli locali e viste read-only

La CLI locale divide il confine in comandi espliciti:

- `email-capability` mostra identità adapter/parser, profili, disponibilità del target e limiti;
- `email-source-create`, `email-source-list`, `email-source-show`, `email-source-state`,
  `email-source-schedule` e `email-source-remove` gestiscono configurazione e tombstone;
- `email-intake-queue`, `email-intake-run`, `email-intake-jobs`, `email-intake-job` e
  `email-intake-cancel` gestiscono il lavoro durevole;
- `email-messages`, `email-message`, `email-threads`, `email-thread`, `email-attachments` e
  `email-attachment` ispezionano rappresentazioni locali limitate;
- `email-derived-remove` e `email-derived-rebuild` cambiano soltanto lo stato email derivato.

La sequenza minima dell'operatore è: creare una Source con percorso locale e profilo esatti,
cambiarne lo stato in `enabled`, accodare l'intake per quella Source, quindi eseguire esplicitamente
il job restituito. Creazione e abilitazione restano separate; l'accodamento non aggira i gate di
capability, stato Source o snapshot.

```bash
provelume email-source-create INSTANCE --name "Messaggio locale" \
  --path /percorso/al/messaggio.eml --profile eml-file-v1
provelume email-source-state INSTANCE SOURCE_ID enabled
provelume email-intake-queue INSTANCE SOURCE_ID
provelume email-intake-run INSTANCE JOB_ID
```

Per il profilo Ubuntu obiettivo usa `maildir-cur-new-v1` con la root Maildir esplicita. I risultati
di creazione e accodamento restituiscono gli ID opachi Source e job usati dal comando successivo.

La superficie supportata copre:

- creazione esplicita di una Source email locale e ispezione di capability/profilo/limiti;
- abilitazione, pausa o disabilitazione e richiesta Run now;
- osservazione o cancellazione del lavoro durevole;
- elenco e ispezione sicura di messaggi, thread osservati e allegati;
- rimozione o ricostruzione di una rappresentazione email derivata;
- visualizzazione dell'idoneità OCR senza avviare OCR;
- rimozione tombstone della Source senza cancellare acquisizioni precedenti.

L'API read-only espone gli stessi read model sanitizzati sotto `/api/v1/email/capability`,
`/sources`, `/jobs`, `/messages`, `/threads` e `/attachments`, con route item per ogni identità
conservata; restituisce `405` ai tentativi di mutazione. Le mutazioni Browser esistono soltanto su
`/email`, superficie loopback protetta dal contratto CSRF corrente. S03 non aggiunge upload HTTP o
endpoint remoto di intake.

Gli errori chiusi distinguono capability/Source disabilitata, profilo/piattaforma non supportati,
percorso mancante o non sicuro, mutazione durante la lettura, limite superato, messaggio/MIME
malformato, transfer encoding invalido, collisione dell'identità dichiarata, timeout,
cancellazione, lease scaduta/recuperata, artefatto derivato invalido ed errore interno.

## Separazione OCR e rete

La capability può indicare se byte esatti e media type di un allegato sono idonei per il contratto
OCR S01/S02. È soltanto un'informazione. L'intake email non abilita, accoda o esegue OCR:
l'operatore deve abilitarlo ed eseguirlo separatamente ed esplicitamente. L'envelope della
capability email riporta stato, motivo e media type OCR verificati separatamente in
`attachment_ocr`; `intake_dependency: false` indica che la disponibilità email non implica né
richiede quella OCR.

Capability discovery, lettura Source, parsing MIME, rebuild derivato e ispezione read-only non
richiedono rete. Non aprono socket, risolvono DNS, recuperano avatar, seguono link, caricano immagini
remote, scaricano parser o usano fallback provider. Abilitare una Source email locale non abilita
`network.external_access` e non aggiunge origin.

Gmail, Google Drive, IMAP, POP, SMTP, invio, discovery account e cursor/refresh provider sono
assenti. Gmail/Drive restano forecast `0.9/S04`, non attivato.

## Packaging e limiti noti

S03 non aggiunge dipendenze runtime. Wheel e sdist contengono codice Provelume per adapter/seam e
schemi; non aggiungono parser MIME esterni, SDK provider, librerie native o payload mailbox.
L'installer Windows usa la standard library CPython già presente nel runtime frozen. Nessun
componente viene scaricato a runtime. La SBOM della release continua a descrivere i package
realmente costruiti, senza inventare un componente `email` versionato separatamente.

La baseline non supporta mbox, cartelle Maildir annidate, Maildir su Windows, mailbox remote o
rimovibili, PST/OST, espansione archivi, HTML attivo, contatti/calendario/task, invio messaggi,
classificazione semantica, AI/RAG, verifica di autenticità o merge cross-Source. `0.9.0` non è
pubblicata e nessuna modifica S03 crea tag, release o asset.

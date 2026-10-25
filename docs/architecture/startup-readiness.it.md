# Avvio e readiness del backend posseduto dal Pannello

Contratto di sviluppo Concordia S01 / [#393](https://github.com/gabned/provelume/issues/393),
dopo il [passo 0 accettato](concordia-step-0.md). Qualifica e accettazione sono nel ledger
della PR owner. La release pubblicata resta Entitas; l'identità cambia solo nel workstream
finale Concordia. [Contratto inglese](startup-readiness.md).

## Proprietà e autorità

Un solo `ManagedStartup` possiede preparazione, creazione del figlio, bootstrap, sonde seriali,
osservazione del processo e cleanup. Tk riceve gli eventi: I/O di avvio e ricevute dell'endpoint
sono eseguiti dal worker. Apri ripetuto non crea figli o nuove deadline. Ogni callback verifica
tentativo corrente, process object posseduto, Instance e porta; un tentativo annullato non apre
pagine. Cambio Instance e riavvio attendono il cleanup confermato.

Il Pannello normale viene renderizzato prima dell'apertura obbligatoria iniziale dell'Instance,
dell'inizializzazione al primo avvio e della dichiarazione della preferenza per gli aggiornamenti.
Queste operazioni sono nello stesso worker posseduto e nel budget di preparazione esistente
di 10 secondi. L'autorizzazione alla creazione è consumata una sola volta: i tentativi successivi
non ricreano implicitamente un'Instance mancante. Le nuove directory locali mantengono guard
fisici sui parent e non seguono alias; directory vuote parziali restano visibili dopo un'interruzione.
Dopo un annullamento con cleanup confermato è possibile riprovare; un'Instance osservata come
mancante o non valida mantiene messaggi e controlli di recupero. La diagnostica statica del layout
prepara il proprio fixture temporaneo esplicito e non avvia backend.

Canale e controllo aggiornamenti all'avvio restano disabilitati finché la preparazione iniziale
non è risolta; eventi dei widget già accodati non possono salvare preferenze durante questa fase.
Gli eventi successivi dell'avvio non sostituiscono revisioni più recenti delle impostazioni.
Disattivare il controllo all'avvio invalida i risultati pendenti prima della scrittura fallibile
della policy nell'Instance, come già avviene per il cambio di canale.
Dopo un errore/annullamento iniziale confermato torna disponibile la verifica manuale degli
aggiornamenti con la conferma esistente; nessuna verifica automatica o deroga ai consensi.

Anche l'ispezione della policy degli aggiornamenti automatici avviene fuori da Tk, conservando
i controlli indipendenti di consenso globale e del componente. Canale, generazione e Instance
restano quelli della richiesta: un nuovo tentativo, un cambio Instance o Esci impediscono che
quel risultato avvii una nuova verifica.

Dopo la conferma esplicita esistente per l'installer, l'intento pendente resta legato alla richiesta
di aggiornamento e all'owner del cleanup. L'installer parte soltanto dopo la conclusione di
quell'owner e senza backend ancora vivo. Cleanup non confermato, Esci, owner sostituito o
richiesta superata non avviano l'installer. Download, firma e gate di pubblicazione restano quelli
esistenti.

Restano obbligatori ispezione dell'installazione e apertura/recupero dell'Instance. La
preparazione parent verifica i guard della directory locale, esegue la preparazione esistente
dell'Instance e mantiene aperta la directory fisica durante binding e avvio. Il figlio apre la
stessa directory con guard e ripete l'inizializzazione applicativa obbligatoria. Sostituzioni,
identità non disponibili, catene reparse ed errori critici bloccano l'avvio. Nessun nuovo lock
globale, stato canonico, migrazione o bypass del recupero. Dopo l'osservazione verificata si
rilasciano i guard di startup; le successive operazioni restano soggette al lifecycle esistente.

## Contratto privato

Il launcher aggiunge un flag interno al comando backend fisso. Un solo frame stdin contiene
lunghezza unsigned big-endian di quattro byte e massimo 256 byte JSON UTF-8, con sole chiavi
`version: 1`, `startup_id` (16 byte casuali, 32 caratteri hex minuscoli), `key` (32 byte casuali,
64 caratteri hex minuscoli). Campi duplicati/extra, troncamenti, byte successivi e altre codifiche
sono rifiutati. Il parent scrive una volta e chiude la pipe.

Il figlio frozen senza console legge l'handle stdin OS anche con `sys.stdin=None`. Rende i
relativi handle non ereditabili e rimuove la pipe consumata dallo slot standard-input Windows
prima di avviare worker. La chiave non entra in argv, ambiente, file, URL, diagnostica o
parametri dei worker. I riferimenti segreti sono rilasciati col tentativo; non si promette
cancellazione fisica garantita della memoria Python.

Soltanto il figlio con bootstrap registra `GET /internal/startup-readiness`; il normale
`--serve` mantiene la route assente. Nessuna query; una sola intestazione
`X-Provelume-Readiness-Challenge` con nonce fresco di 32 byte hex minuscoli. Il client usa
soltanto IPv4 loopback e porta selezionata, senza DNS, proxy, redirect, porta alternativa o
fallback a `/health`.

Risposta JSON UTF-8 entro 2.048 byte e campi esatti: `contract`, `version`, `startup_id`,
`challenge`, `instance_binding`, `port`, `backend_state`, `reason`, `diagnostics_state`, `proof`.
I booleani non sono interi. Versione 1, contract `provelume.startup-readiness`.
`ready/operational` usa HTTP 200; `starting/initializing` e
`failed/{configuration_invalid,integrity_failed,initialization_failed}` usano HTTP 503.
La diagnostica è indipendente: `not_requested | pending | complete | failed | unavailable`.
Lo startup dichiara la diagnostica d'archivio `not_requested` e non avvia scansioni.

Ogni campo HMAC è UTF-8 preceduto dalla lunghezza unsigned big-endian di quattro byte;
gli interi sono stringhe decimali senza segno. Binding: `provelume.instance-binding.v1`,
startup ID, ID canonico Instance, root binding fisico, `127.0.0.1`, porta. Il root binding è
`win32.file-id.v1:` seguito dall'hex del volume serial FileIdInfo unsigned big-endian di otto
byte e dei 16 byte FileId originali. I test Linux di riferimento usano il dominio distinto
`posix.file-id.v1:` con device/inode di otto byte. Il path non è identità. ID canonico entro
1.024 byte UTF-8.

Campi proof, nell'ordine: `provelume.startup-readiness.proof.v1`, contract, versione, startup
ID, challenge, Instance binding, porta, stato backend, motivo, stato diagnostica. Confronti
binding/proof a tempo costante. Nonce vecchi, schema malformato, versione non supportata,
Instance/root/porta diversi o MAC errata terminano il tentativo. Il binding distingue il
figlio da un listener estraneo, senza promettere difesa da processi compromessi con accesso
alla memoria o agli handle dello stesso utente.

READY segue controlli installazione, Instance/schema/recupero, servizi/middleware e lifespan
applicativo. Installazione modificata è terminale; evidenza di release esplicitamente richiesta
ma mancante non diventa successo. L'ispezione del sorgente editable mantiene il proprio stato
non disponibile, senza attestazione d'integrità installata. Il frozen privato richiede integrità
del pacchetto verificata: conserva i sorgenti Python della wheel accanto al PYZ perché il
controllo RECORD esistente possa verificare ogni byte richiesto. Evidenze mancanti, modificate
o non disponibili impediscono READY. RECORD verifica il contenuto locale del pacchetto, non
la provenienza dell'eseguibile o l'autenticazione dell'editore. `/health` conserva schema e
controlli profondi. Nel frozen i metadati sono quelli canonici della versione in esecuzione
nel root del loader; restano i controlli di tree importato, versione e RECORD. I metadati
storici dell'aggiornamento sono conservati, senza selezione per ordine di discovery o fallback
da un RECORD corrente fallito. Evidenze correnti mancanti o incoerenti falliscono chiuse.
Readiness è osservazione dell'avvio, non salute permanente o prova per-Version.

## Lavoro finito e arresto

| Limite | Valore |
| --- | --- |
| Preparazione parent | 10 s |
| Spawn e bootstrap | 5 s |
| Readiness del figlio | 60 s |
| Startup totale assoluto | 75 s |
| Sonda HTTP completa | 1 s su connessione, header, corpo e verifica |
| Intervallo / massimo sonde | 250 ms / 240, una in volo |
| Cleanup | 4 s cooperativo/terminate, poi 2 s di escalation circoscritta |

Il tempo inutilizzato non estende altre fasi. Le letture sono limitate e la deadline monotona
assoluta comprende risposte lente byte per byte. L'annullamento invalida subito gli effetti UI.
I/O OS bloccante può oltrepassare il budget: worker e risorse rimangono posseduti; il risultato
tardivo viene riconciliato, senza accettarlo o abbandonarlo.

Su Windows un evento manual-reset del solo tentativo chiede lo shutdown normale a Uvicorn.
Nome: `Local\Provelume.Startup.Stop.` più HMAC-SHA-256 sui campi framed
`provelume.startup-stop.v1` e startup ID, con la chiave bootstrap. Il parent crea un evento
nuovo, rifiutando collisioni; il figlio lo apre solo per sincronizzazione. Nome e handle non
entrano nella diagnostica. Nessun nuovo endpoint HTTP mutativo o di controllo.

Il worker conserva l'owner del controllo prima di acquisire il primo handle nativo. Una
preparazione fallita con chiusura non confermata resta posseduta anche senza figlio avviato.
Prima del bootstrap il parent assegna il figlio a un Job Windows anonimo con KILL_ON_JOB_CLOSE,
senza nuovi limiti CPU/memoria/numero processi. Il packaging `onedir` supportato non ha un
bootloader separato; i worker applicativi ereditano il Job e mantengono i propri limiti.
L'escalation termina soltanto quel Job/processo posseduto e verifica uscita del processo e
zero membri attivi prima di rilasciare gli handle. Il riferimento POSIX conserva SIGTERM
e l'escalation del processo posseduto.

`STOP_UNCONFIRMED` mantiene l'owner quando figlio, discendenti o risorse sono attivi/ignoti.
Non dichiara retry concorrente, riavvio differito, cambio Instance o Esci completato. Il Pannello
resta disponibile per i dettagli locali; termina soltanto dopo riconciliazione. Ricevute
known-good/rollback dell'endpoint conservano le revisioni esistenti; un esito vecchio non
sovrascrive preferenze successive.

La chiusura ambigua di un descrittore directory è una condizione OS non supportata. Il numero
non viene riutilizzato per tentare altre chiusure dopo un possibile riuso. L'owner resta non
confermato e richiede recupero circoscritto del processo/OS; un nuovo avvio deve rivalidare e
recuperare l'Instance. Nessun Esci completato o sostituzione concorrente è dichiarato.

Dettagli locali: massimo 32 eventi con fase/codice/tempi ammessi ed eventuale exit code.
Niente documenti, path, ID canonici, chiavi, eccezioni/stderr grezzi, challenge o proof.
Nessun upload o copia automatica.

## Proiezione pagine e qualifica

Ricerca vuota/soli spazi e Informazioni usano soltanto l'identità configurata reale nel contesto
condiviso, senza inventare contatori o salute. I filtri conservano le fonti dati esistenti;
la ricerca positiva mantiene controlli d'indice/operazione e contesto profondo. Altre pagine,
`/health`, campi API e semantica dei processi canonici sono preservati.

[Matrice di qualifica](../qualification/concordia-startup-readiness.md): protocollo, lifecycle,
controlli Windows nativi, subprocess sorgente e trasporto frozen sono colonne distinte. Lo
smoke installato conserva i 30 secondi del normale avvio. Non sostituisce le prove effettive
Pannello/tray/browser e Windows 11 25H2 Home/Pro.

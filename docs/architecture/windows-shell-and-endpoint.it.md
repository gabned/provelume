# Architettura della shell Windows e dell'endpoint locale

Questo documento definisce in italiano il contratto architetturale dell'inedito `0.9/S07`.
L'identità pubblica del prodotto resta `0.8.0`.

## Confini

La shell controlla soltanto percorso del launcher, preferenza esplicita degli aggiornamenti,
lingua, porta loopback, comportamento tray, avvio al login e tema. Non può modificare Originals,
Documents, Versions, Acquisitions, Sources, stato dei provider o configurazione canonica di
un'istanza. Lo stato shell è in `%LOCALAPPDATA%\Provelume\launcher.json`, il runtime in
`%LOCALAPPDATA%\Programs\Provelume` e l'istanza predefinita resta
`%USERPROFILE%\Documents\Provelume`.

| Superficie | Lettura | Mutazione | Autorità |
| --- | --- | --- | --- |
| `GET /api/v1/shell` | endpoint/servizio/capacità sanificati | nessuna | API pubblica read-only |
| `/settings/shell` GET | impostazioni locali | nessuna | Browser loopback |
| `/settings/shell` POST | revisione corrente | preferenze limitate | loopback + CSRF + nonce + revisione |
| CLI shell | configurazione/diagnostica | set/reset/import esplicito | processo locale + lock |
| installer | verifica stato esistente | inizializza nuove preferenze | setup per utente con rollback |
| tray | stato ed endpoint | apri/riavvia/esci | unico processo shell installato |

## Configurazione chiusa

Lo schema 2 accetta solo i campi documentati. `host` deve essere `127.0.0.1`, la porta un intero
tra 1024 e 65535, il tema `system`, `light` o `dark`, la lingua `en` o `it`. I booleani non sono
interi. Documenti oltre 64 KiB, campi sconosciuti, schemi invalidi, symlink e reparse point sono
rifiutati. Lo schema 1 viene letto e migrato soltanto al successivo salvataggio esplicito.

Stato assente o invalido produce valori sicuri e un warning, senza riscrivere il file in lettura.
La mutazione usa lock di sistema non bloccante, revisione, file temporaneo nella stessa directory,
flush/fsync e replace atomico. Il recupero esplicito elimina al massimo 32 temporanei corrispondenti
e nessun altro percorso.

## Ciclo dell'endpoint

- Default: `http://127.0.0.1:44851`.
- Override esplicito: `--port` vale solo per il processo e ha precedenza massima.
- Override persistito: validato, reversibile e preservato durante upgrade.
- Endpoint assente, legacy o corrotto: `44851`, con warning quando pertinente.
- Porta occupata: un bind loopback fail-closed dell'installer si ferma prima della copia; il codice
  installato ricontrolla prima dell'apply atomico e il preflight non modifica la configurazione.
- Race dopo il preflight: l'avvio fallisce, può ripristinare l'esatto valore noto precedente e
  attende un riavvio esplicito.
- Avvio riuscito: azzera `restart_required` e promuove la stessa porta a valore noto valido.
- Nessuna porta casuale, host remoto, wildcard, DNS, firewall o fallback di rete.

Uvicorn riceve soltanto un host loopback validato e il middleware rifiuta Host non locali. Ogni
mutazione Browser richiede autorizzazione del servizio, client loopback, policy same-origin senza
script, CSRF, riferimento monouso valido dieci minuti (massimo 64) e revisione esatta. Richieste
consumate, ripetute o stale non mutano lo stato.
Campi sconosciuti, obbligatori mancanti o duplicati falliscono prima di consumare il riferimento
monouso. L'ispezione distingue endpoint attivo del servizio e target configurato per il riavvio.

## Tray e servizio

Un mutex nominale protegge la shell. Il default installato crea un'icona nativa nell'area di
notifica e avvia un solo servizio figlio. Chiudere la finestra la nasconde solo se il tray
configurato è disponibile; l'opt-out esegue un'uscita controllata. Apri e Impostazioni riusano il
figlio pronto. Riavvia ferma e attende prima della sostituzione. Un crash è annunciato e non viene
ritentato automaticamente. Esci rimuove il tray e termina/attende/kill entro limiti documentati.
L'avvio al login è una scelta distinta e usa un solo eseguibile installato, assoluto e quotato;
l'uninstall rimuove soltanto il riferimento Run ormai inutilizzabile. La modalità esplicita
`--tray` nasconde la finestra iniziale solo dopo l'avvio riuscito del tray nativo; se il tray non è
disponibile resta una finestra controllata e visibile.

## Identità, packaging e firma

Il manifest collega SVG pubblico, generatore deterministico, ICO e nove dimensioni. PyInstaller
incorpora icona e metadata veritieri `0.8.0`; Inno li usa per setup, uninstall e shortcut. Gli
shortcut e il processo usano `Provelume.Desktop` prima della creazione delle finestre.

Gli artefatti S07 sono esplicitamente non firmati. Manifest e diagnostica riportano `unsigned` e
`publisher_authentication: not_established`. Il metadata descrittivo `Neobeta` non autentica
l'editore. Una release firmata resta bloccata fino a certificato autorizzato, catena valida,
timestamp, subject atteso ed evidenza permanente sull'artefatto esatto. Il repository non contiene
certificati, chiavi, password o secret.

## Trasferimento preferenze e privacy

Export/backup contiene soltanto porta, tray, preferenza login, tema e lingua. Import/restore valida
dimensione, campi, tipo di percorso e disponibilità prima dell'applicazione atomica. Non include
percorso dell'istanza, dati Source/provider o riferimenti credenziali. La diagnostica contiene solo
schema, capacità, codici di stato, limiti, endpoint e firma: non registra query URL, contenuto,
path Source, token, CSRF o nonce.

## UX e accessibilità

Cinque gruppi etichettati separano conoscenza, stato operativo, configurazione, manutenzione e
supporto. Le icone integrano il testo. I temi system/light/dark preservano focus e contrasto;
`forced-colors`, zoom/reflow al 200% e `prefers-reduced-motion` hanno regole esplicite. Form, errori,
stati e menu nativi hanno label, descrizioni, live region e accesso da tastiera. I cataloghi EN/IT
espongono le stesse chiavi semantiche. Markup, URL, formule, escape e payload simili a script restano
dati inerti grazie ad autoescape e CSP senza script.

## Qualification

La matrice exact-head richiede Ruff, tutta la suite locale, icona riproducibile, regressioni per
endpoint/sicurezza/accessibilità, Public CI, trusted-base, smoke Windows shell, cross-source,
transcript, OCR, email e Google synthetic. Il Core Windows candidate deve concludersi nel budget
permanente. Fallimento, cancellazione o timeout restano gate non verdi.

# Rappresentazioni universali e supporto effettivo

Questo contratto per sviluppatori descrive la base additiva `0.10/S01`. Non implementa capacità
per foto, audio, video o AI e non modifica l'identità pubblicata del pacchetto `0.9.0`.

## Autorità e identità

Un Original e la relativa DocumentVersion canonica restano l'autorità. Una rappresentazione è
derivata, attribuibile, rimovibile e ricostruibile. Il suo ID stabile è l'identità SHA-256 di:

1. ID della Version esatta e SHA-256 dell'Original;
2. ID e versione della recipe e fingerprint delle impostazioni canoniche;
3. descrittori ordinati degli output e fingerprint di SHA-256/dimensione.

Data di creazione, stato del lifecycle e posizione di storage non cambiano implicitamente questa
identità del contenuto. Una recipe o un output differenti producono un ID differente. Le relazioni
`previous` e `parent` preservano la storia di derivazione invece di sostituire un risultato.

`representation_bundle.schema.json` è il JSON Schema pubblico; gli enum di dominio pubblici sono
in `provelume.representations`. La validazione runtime è rigorosa e rifiuta campi sconosciuti o
incompleti. Ogni bundle registra versioni di componente e adapter, impostazioni, warning chiusi,
tipo/percorso/hash/dimensione degli output, lifecycle, disponibilità, provenance, correzioni,
anchor, limiti di sicurezza e invarianti dell'autorità immutabile. I bundle disponibili non hanno
blocchi; quelli degradati o non disponibili riportano un motivo chiuso e possono indicare il
componente mancante.

## Operazioni di supporto indipendenti

`representation-support-registry.schema.json` valida il registry versionato incluso nel
pacchetto. Contiene una riga per ogni profilo e per ogni operazione:

- `preserve`: conserva byte e identità esatti;
- `inspect`: legge fatti strutturali entro limiti chiusi;
- `extract`: deriva contenuti come testo normalizzato;
- `preview`: presenta una vista derivata inerte;
- `local_enrich`: esegue un componente locale installato esplicitamente;
- `ai_enrich`: riservato e non disponibile con `not_implemented` in S01.

`declared_state` è `supported`, `optional` o `unsupported`. `effective_state` è `available`,
`degraded` o `unavailable`. Una riga degradata/non disponibile ha un motivo chiuso e può indicare
il componente mancante. Una riga disponibile non ha nessuno dei due. Preserve non implica mai
un'altra riga né l'indicizzazione per la ricerca.

Le righe OCR sono risolte dalla configurazione locale e dall'evidenza dei componenti senza
richieste di rete. OCR disabilitato riporta `disabled_by_configuration`; motore, renderer o
language pack mancanti indicano il componente esatto. Le altre righe S01 usano dichiarazioni
first-party incluse nel pacchetto.

## Anchor e correzioni

Ogni anchor ripete gli ID esatti di Version e rappresentazione. Gli anchor pagina hanno un numero
positivo. Gli anchor tempo hanno limiti ordinati e non negativi in millisecondi. Gli anchor regione
contengono pagina e rettangolo positivo. `slide` e `symbol` restano riservati e contengono solo una
riserva esplicita. S06 attiva in modo additivo forme target-v1 chiuse per `sheet`, `cell` CSV/XLSX e
`member` ZIP; la riserva esplicita precedente resta valida, quindi i bundle schema-v1 esistenti non
richiedono migrazione. Un target tipizzato vale solo per profilo e coordinate/percorso/hash esatti.

Le correzioni riferiscono un anchor, vincolano checksum prima/dopo e sono sempre reversibili. Sono
annotazioni su una rappresentazione derivata, mai modifiche a Original, record canonici o dati del
provider.

## Lifecycle, percorsi e limiti

Bundle e output nativi restano sotto
`state/derived/representations/<representation-id>/`. I percorsi devono essere relativi,
normalizzati, compatibili con Windows, distinti senza dipendere da maiuscole/minuscole e privi di
collisioni file/directory. I massimi v1 sono 1.000 output, 100.000 anchor, 10.000 correzioni, 1.000
warning, 16 GiB per output, 512 GiB totali e rapporto di espansione 1.000x. Un bundle può scegliere
limiti inferiori, mai superiori.

I percorsi devono inoltre essere normalizzati NFC e la validazione runtime applica ogni limite
inferiore scelto per percorso o segmento. La deep validation risolve Version e Original di ogni
bundle nei record canonici e ricontrolla i byte dell'Original autorevole prima di accettare lo
stato derivato.

La rimozione elimina solo l'albero di output nativo dopo aver scritto una ricevuta derivata. Il
rebuild accetta byte rigenerati solo se hash/dimensione e fingerprint del bundle attivo coincidono
con la ricevuta. Un errore elimina il rebuild parziale e lascia invariati Original, record canonici
e dati provider.

## Vista di compatibilità Lectio

`lectio-representation-compatibility.json` mappa senza conversione:

- estrazione e bundle documentali;
- bundle OCR locale;
- intake email locale;
- evidenza Google Gmail/Drive in sola lettura;
- revisioni transcript SRT e WebVTT;
- finding di qualification cross-source.

La vista riporta profilo, posizioni esistenti e conteggio visibile. Non riscrive i file e non
presenta un bundle legacy come bundle nativo S01. Le Instance schema-2 restano leggibili senza
migrazione eager e senza sidecar `.md` accanto a un Original.

## Read model unico e comportamento portabile

`RepresentationReadModel` fornisce le stesse chiavi a service, comandi CLI
`representation-support`/`representations`, endpoint `/api/v1/representations*` e pagina Browser
EN/IT `/representations`. Ogni risultato dichiara `network_used: false` e `mutated: false`.

I backup includono già gli artefatti durevoli in `state/derived`. L'export portabile conserva
`state_artifacts: include` sia in modalità rebuild sia include; restore/import eseguono la deep
validation prima del commit. `representation_state_findings` rende non valida la Instance di
staging se trova bundle malformati, posizioni non sicure, output mancanti, hash/dimensioni errati o
ricevute di rimozione alterate.

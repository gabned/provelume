# Esecuzione OCR locale e document bundle

Stato: `0.9/S01` ha definito il contratto pubblico tramite
[#5](https://github.com/gabned/provelume/issues/5) e
[PR #138](https://github.com/gabned/provelume/pull/138). `0.9/S02 — Bounded local OCR and
document bundles` lo implementa sotto la issue owner
[#140](https://github.com/gabned/provelume/issues/140) e la
[PR #141](https://github.com/gabned/provelume/pull/141). Lectio resta sviluppo non pubblicato:
package, runtime e build identity incorporata rimangono `0.8.0`.

I record normativi sono:

- [`ocr_contract.py`](../../core/provelume/ocr_contract.py) e
  [`ocr_contract.schema.json`](../../core/provelume/ocr_contract.schema.json) per impostazioni,
  capability, richieste e risultati di pagina;
- [`ocr_bundle.schema.json`](../../core/provelume/ocr_bundle.schema.json) per manifest e page
  envelope del document bundle completo, promosso atomicamente;
- [ADR 0014](../adr/0014-local-ocr-contract-and-packaging.md) per la scelta del motore in S01 e
  [ADR 0015](../adr/0015-bounded-local-ocr-execution.md) per il percorso eseguibile S02;
- [`tesseract-5.5.3.json`](../../packaging/ocr/tesseract-5.5.3.json) e la
  [BOM dei componenti esterni qualificati](../../packaging/ocr/qualified-local-components.cdx.json)
  per il perimetro tecnico e di licensing provato.

## Confine inderogabile

- L'OCR è opzionale, locale e offline. Il default è `disabled` e in tale stato la probe non cerca
  né avvia il motore.
- Provelume non scarica né installa componenti a runtime, non contatta provider e non effettua
  fallback remoto. Motore, renderer, decoder e language pack sono dipendenze locali predisposte
  dall'operatore.
- L'Original acquisito esatto resta autorevole. SHA-256 e lunghezza, insieme al fingerprint
  completo della conoscenza canonica, sono controllati prima e dopo pianificazione, esecuzione,
  errore, cancellazione, rimozione e ricostruzione.
- Il testo OCR è un derivato non verificato. Non diventa automaticamente conoscenza canonica né
  testo verificato. La confidence è evidenza del motore, non una dichiarazione di verità.
- Le osservazioni di layout, tabelle, barcode e QR restano separate dal testo. L'adapter Tesseract
  baseline non ne produce e lascia vuote queste collezioni.

## Componenti e matrice qualificati

Il motore di riferimento resta Tesseract CLI 5.5.3 con licenza Apache-2.0. L'adapter accetta una
versione dichiarata in `>=5.3,<6`, risolve l'eseguibile configurato nel path locale effettivo e
registra entrambi. Prima del job controlla l'elenco dei language pack installati. Non installa mai
Tesseract o i pack.

La rasterizzazione PDF usa pypdfium2 5.13.0 con PDFium 153.0.7999.0. La decodifica di TIFF, PNG,
JPEG e BMP usa Pillow 12.3.0. Queste wheel e i relativi componenti nativi restano esterni a ogni
package Provelume. L'unica qualifica S02 con componenti reali è:

| OS | Architettura | Python | Motore/pack | Renderer/decoder | Input |
| --- | --- | --- | --- | --- | --- |
| Ubuntu 24.04 | x86-64 | 3.12 | Tesseract 5.x della distribuzione e `eng` locale; CI registra l'identità esatta | pypdfium2 5.13.0 / PDFium 153.0.7999.0 / Pillow 12.3.0 | PDF scansionato, TIFF, PNG, JPEG, BMP |

La suite multipiattaforma verifica anche la pulizia dei processi su Windows, ma S02 non qualifica
alcuna combinazione reale motore/renderer per Windows. Restano quindi non qualificati Windows
x86-64 e ARM64, Linux ARM64 e macOS x86-64/ARM64. Non è una promessa generale per PDF, codec o
lingue ulteriori.

## Preparazione locale esplicita

Dopo aver creato il normale ambiente Provelume, l'operatore installa i componenti esterni tramite
una propria procedura di sistema/ambiente. Per il profilo Ubuntu qualificato, il modello CI
equivale a:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
.venv/bin/python -m pip install 'pypdfium2==5.13.0' 'Pillow==12.3.0'
```

Sono esempi di setup, non comportamento del prodotto a runtime. Il workflow CI scarica le due
wheel esatte in una fase di provisioning separata, verifica gli SHA-256 registrati, le installa
offline dalla wheelhouse e soltanto dopo esegue lo smoke test del prodotto.

Abilitare esplicitamente la capability e verificarla prima di accodare lavoro:

```bash
.venv/bin/provelume ocr-configure INSTANCE \
  --mode automatic \
  --language eng \
  --engine-executable /usr/bin/tesseract
.venv/bin/provelume ocr-capability INSTANCE
```

Opzioni `--language` ripetute definiscono un insieme ordinato esplicito. `--tessdata-path` può
indicare una directory di pack locali gestita dall'operatore. Gli stessi controlli sono disponibili
nella pagina Browser `/ocr`, vincolata al loopback e protetta da token CSRF per-processo. Le route
HTTP API restano read-only.

Il default disabilitato completo è:

```yaml
ocr:
  schema_version: 1
  mode: disabled
  engine: tesseract-cli
  engine_executable: tesseract
  tessdata_path: null
  renderer: pdfium-pillow
  render_dpi: 300
  languages: [eng]
  language_detection:
    mode: disabled
    candidates: []
  automatic:
    min_reliable_characters: 32
    min_printable_ratio: 0.85
  limits:
    max_input_bytes: 268435456
    max_pages: 200
    max_page_pixels: 80000000
    max_total_pixels: 500000000
    max_decompressed_page_bytes: 335544320
    max_decompression_ratio: 100
    max_temp_bytes: 1073741824
    max_seconds_per_page: 60
    max_total_seconds: 900
    max_output_chars_per_page: 500000
```

La configurazione può abbassare ma non superare questi massimali. Campi sconosciuti o valori non
validi falliscono in modo chiuso.

## Modalità e regola automatica deterministica

| Modalità | Regola di esecuzione |
| --- | --- |
| `disabled` | non effettua probe, pianificazione, accodamento o esecuzione OCR |
| `automatic` | salta soltanto se il testo PDF incorporato affidabile contiene almeno 32 caratteri stampabili non whitespace e rapporto stampabile almeno 0,85; altrimenti accoda OCR |
| `forced` | accoda ogni pagina valida del documento |
| `selected-page` | richiede pagine 1-based ordinate, univoche, non vuote e interne al documento |

In questo perimetro soltanto l'estrattore `pypdf` del testo incorporato costituisce evidenza di
testo affidabile. Metadati immagine come formato e dimensioni non sopprimono mai l'OCR automatico.
Regola, generatore, numero caratteri e rapporto sono persistiti con la richiesta durevole. Da una
a otto lingue sono esplicite; la baseline passa a Tesseract esclusivamente i pack selezionati e
presenti localmente.

Accodamento ed esecuzione di una Version esatta:

```bash
.venv/bin/provelume ocr-queue INSTANCE VERSION_ID --mode forced --language eng
.venv/bin/provelume ocr-run INSTANCE JOB_ID
.venv/bin/provelume ocr-job INSTANCE JOB_ID
```

Per scegliere pagine usare `--mode selected-page --page 1 --page 3`. Uno skip `automatic` restituisce
la decisione deterministica ma non crea lavoro per il motore.

## Processo e input ostili

La pianificazione verifica prima tipo media, estensione e firma, byte input, numero pagine, pixel
per pagina e totali, byte decodificati e rapporto di decompressione. PDFium non passa mai un PDF a
Tesseract: produce un PNG limitato alla volta. Pillow decodifica soltanto le famiglie dichiarate.
Input corrotti, non supportati o oltre limite falliscono senza provare altri decoder o provider.

Tesseract usa `shell=False`, un vettore di argomenti da allowlist, un ambiente figlio minimo e senza
contenuti e una directory privata per pagina. Stdout, stderr e file prodotti sono sorvegliati
durante il processo. Sono applicate deadline per pagina e complessive. Timeout e cancellazione
terminano il process group POSIX o il process tree Windows prima della pulizia. Exit code non zero,
TSV assente, malformato/incompleto o eccessivo sono errori chiusi distinti.

È contenimento di processo, non un sandbox di sicurezza generale. S02 non dichiara sandbox OS,
container, seccomp o quote CPU/memoria indipendenti. Le directory temporanee POSIX usano mode
`0700`; Windows usa le ACL ereditate dall'utente corrente. Solo Ubuntu x86-64 possiede la qualifica
con componenti reali descritta sopra.

## Lifecycle durevole e bundle

La chiave di idempotenza lega Original, Version, versione contratto, pagine, modalità, lingue,
impostazioni e identità di adapter, motore, renderer e decoder. Il journal fornisce lease esclusiva,
heartbeat, retry limitato e receipt terminale. Ogni pagina completata produce un checkpoint di
lavoro vincolato da checksum. Dopo lease scaduta o crash, le pagine concluse vengono riprese senza
essere pubblicate o ricalcolate; un errore transitorio ritenta la pagina incompleta.

Solo un documento completo viene promosso atomicamente sotto `state/derived/ocr-bundles/`. Il
manifest contiene stato job, identità Original/Version/Document, impostazioni e provenienza dei
componenti, riferimenti e hash stabili di risultato/testo per pagina, warning, incertezza e proprietà
di rimozione/ricostruzione. Il risultato pagina contiene testo, coordinate e confidence quando
prodotti, oltre all'hash del raster sorgente. Nessun work directory parziale appare come derivato
riuscito.

I controlli locali sono:

```bash
.venv/bin/provelume ocr-jobs INSTANCE
.venv/bin/provelume ocr-cancel INSTANCE JOB_ID
.venv/bin/provelume ocr-bundles INSTANCE --version-id VERSION_ID
.venv/bin/provelume ocr-remove INSTANCE VERSION_ID
.venv/bin/provelume ocr-rebuild INSTANCE VERSION_ID
```

La rimozione elimina soltanto bundle, record di artefatto/provenienza derivati e lavoro riprendibile,
conservando una receipt senza contenuti per ricostruire. La ricostruzione rimuove il derivato,
riaccoda la stessa identità materiale e non modifica Original o conoscenza canonica.

## Capability ed errori

La probe mostra limiti configurati/effettivi, lingue scelte e installate, path risolti di motore e
PDFium, versioni esatte di motore/renderer/decoder/componenti e invarianti di assenza rete. Espone
`available: true` soltanto in `ready`. Gli stati distinguono disabilitato, adapter assente, motore
assente, renderer/decoder assente, versione incompatibile e language pack mancante. L'esecuzione
distingue inoltre input non supportato/corrotto/eccessivo, limiti file/pagine/pixel/decompressione/
temporanei/tempo/output, cancellazione, output motore invalido, errore adapter, violazione contratto
ed errore interno. I messaggi EN/IT sono stabili e non includono contenuti sorgente.

Lo stato read-only è in `/api/v1/ocr/capability`, `/api/v1/ocr/jobs`,
`/api/v1/ocr/jobs/{job_id}` e `/api/v1/ocr/bundles`. I token di lease non vengono mai esposti.
Accodamento, esecuzione, cancellazione, rimozione e ricostruzione restano azioni CLI locali o
Browser loopback protette.

## Packaging, licensing e limiti

Wheel base, sdist e installer Windows includono seam Python e schemi, ma nessun payload Tesseract,
Leptonica, language pack, pypdfium2/PDFium o Pillow e nessuna dipendenza runtime OCR. Gli extra
Python non fingono di installare componenti nativi. La BOM dei componenti esterni è evidenza di
qualifica, non SBOM di una release Provelume. Qualsiasi futura redistribuzione richiede inventario
esatto di binari/codec/pack, digest, licenze/notice, manifest/SBOM di release e test offline.

I limiti S02 includono OCR di testo stampato, page segmentation mode 3 di Tesseract, nessuna
verifica semantica o correzione automatica, nessuna promessa qualificata sulla scrittura manuale,
nessun deskew/preprocessing avanzato automatico, nessun adapter baseline per layout/tabelle/barcode/
QR e nessun supporto oltre la matrice esatta provata. S02 non ha creato tag, release o asset; la
baseline completata viene poi pubblicata in `0.9.0` senza ampliare la matrice.

`0.9/S03` è implementato separatamente tramite issue #143 e la relativa owner PR senza modificare
il contratto OCR S02. `0.9/S04` è stato implementato separatamente e non è attivato da questo
documento.

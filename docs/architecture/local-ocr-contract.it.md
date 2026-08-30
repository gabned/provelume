# Contratto della capability OCR locale

Stato: lavoro di contratto `0.9/S01` attivo in
[#137](https://github.com/gabned/provelume/issues/137) e
[#5](https://github.com/gabned/provelume/issues/5).

S01 definisce un confine OCR locale stabile. **Non** implementa ancora renderer completo, adapter
di processo Tesseract, integrazione nei document bundle o flusso utente di esecuzione. L'OCR non è
quindi ancora una funzione di elaborazione utilizzabile in Provelume.

Il contratto normativo nel codice è
[`ocr_contract.py`](../../core/provelume/ocr_contract.py), lo schema machine-readable è
[`ocr_contract.schema.json`](../../core/provelume/ocr_contract.schema.json) e la decisione tecnica
e di licensing è [ADR 0014](../adr/0014-local-ocr-contract-and-packaging.md).

## Regole di base

- La baseline OCR è locale e offline. Non comprende endpoint cloud o provider remoto.
- La modalità predefinita è `disabled`; in questo stato il reporting non cerca adapter o motori.
- Provelume non scarica a runtime motori o language pack e non prevede fallback impliciti.
- L'Original acquisito esatto rimane autorevole e invariato.
- Testo e osservazioni OCR sono artefatti derivati, eliminabili e ricostruibili.
- Un errore OCR non autorizza modifiche canoniche, cancellazione dell'Original o pulizia automatica
  della conoscenza dell'utente.
- Il primo seam usa Tesseract CLI 5.5.3, ma gli adapter restano sostituibili ed espliciti.

## Configurazione

Le nuove Istanze ricevono l'intera configurazione predefinita disabilitata. Le Istanze esistenti
senza sezione `ocr` mantengono lo stesso comportamento, senza migration:

```yaml
ocr:
  schema_version: 1
  mode: disabled
  engine: tesseract-cli
  languages:
    - eng
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

La configurazione può ridurre questi massimali, ma non aumentarli. Campi, modalità o limiti non
riconosciuti falliscono in modo chiuso.

## Modalità e lingue

| Modalità | Contratto |
| --- | --- |
| `disabled` | non pianifica OCR e non cerca un motore |
| `automatic` | pianifica solo quando il testo affidabile esistente non raggiunge la soglia esplicita di caratteri o rapporto stampabile |
| `forced` | richiede OCR per ogni pagina altrimenti valida del job esplicito |
| `selected-page` | richiede una lista di pagine 1-based ordinata, univoca, non vuota e interna al documento |

Occorre selezionare esplicitamente da uno a otto ID di language pack ordinati. Il rilevamento
opzionale `bounded` può scegliere soltanto tra un massimo di quattro pack già selezionati e
installati. Non può ampliare l'insieme né scaricare un modello. I dati di orientamento/script come
`osd` sono un pack opt-in separato.

## Perimetro degli input

Il contratto accetta PDF scansionati, TIFF, PNG, JPEG e BMP. Tipo media, estensione e firma iniziale
del file devono concordare. WebP, GIF, JPEG 2000 e PNM restano non supportati anche se una specifica
build di Leptonica potrebbe decodificarli.

Tesseract usa immagini raster e non interpreta un modello PDF generale. S02 dovrà scegliere e
qualificare un rasterizzatore PDF limitato, misurare pagine, pixel e byte decodificati prima
dell'esecuzione e registrare in provenienza l'hash esatto dell'immagine di pagina.

Byte, numero di pagine, pixel per pagina e totali, byte decodificati, rapporto di decompressione,
spazio temporaneo e tempi massimi hanno errori chiusi distinti. Input corrotti o non supportati
falliscono senza provare un altro provider.

## Reporting e componenti assenti

Gli stati chiusi sono `disabled`, `adapter-unavailable`, `engine-unavailable`,
`language-pack-missing` e `ready`. Ogni stato non disponibile contiene messaggi stabili inglesi
e italiani; un errore dei language pack indica anche gli ID esatti dei pack mancanti. Ogni report
include questi fatti invarianti:

```json
{
  "network_required": false,
  "runtime_downloads": false,
  "remote_fallback": false,
  "original_mutation": false,
  "canonical_mutation": false
}
```

S01 non include un adapter di esecuzione. Abilitare l'OCR in configurazione produce quindi
`adapter-unavailable`, non un download né un falso stato `ready`.

Il seam dell'adapter riceve un request record esatto e il path di un raster predisposto nella
directory privata del job. La richiesta vincola identità della pagina, tipo media del raster,
fingerprint delle impostazioni, lingue, deadline e limite configurato dei caratteri in output. Il
PDF non viene mai passato direttamente al seam del motore: S02 dovrà predisporre e calcolare l'hash
di un raster limitato per pagina. Un output con provenienza, pagina o limite incoerenti viene
rifiutato.

## Pagina derivata e provenienza

Ogni pagina è identificata da SHA-256 dell'Original, ID della Version canonica, numero pagina
1-based, SHA-256 del raster e tipo media sorgente. Ogni risultato registra inoltre ID/versioni di
motore e adapter, language pack e fingerprint delle impostazioni. Questi dati formano una chiave di
derivazione deterministica per replay e idempotenza.

Testo e span possono essere soltanto `machine-unverified` o `needs-review`: non esiste uno stato
OCR verificato. La confidence è un'osservazione del motore tra 0 e 1. Le coordinate usano pixel
della pagina sorgente e comprendono le dimensioni della pagina. Osservazioni di layout, tabelle,
barcode e QR sono quattro collezioni separate e versionate dall'adapter; restano vuote se
l'adapter non le supporta.

Le pagine committate producono un checkpoint `ocr.page.committed` con sequenza, pagine concluse e
pagina successiva. Il record è compatibile con progressi processed/skipped/error, lease e recovery
content-free introdotti da Vigilia. S01 non registra un job schedulabile.

## File temporanei e cancellazione

Il seam crea per ogni job una directory temporanea privata con mode 0700 sotto una radice locale
esplicita e la rimuove dopo successo o eccezione. S02 dovrà aggiungere isolamento del processo,
limiti CPU/memoria e deadline attorno al motore.

Gli artefatti OCR appartengono soltanto allo stato derivato. La loro rimozione non elimina Original
o record canonici. Una ricostruzione conserva la stessa identità soltanto se byte della pagina,
motore, adapter, lingue e impostazioni non cambiano.

## Stato del packaging

Wheel base, sdist e installer Windows non contengono binari Tesseract o language pack e non
aggiungono dipendenze runtime OCR. Un futuro componente Windows potrà essere solo opt-in,
disabilitato di default e interamente predisposto offline, con sorgente/versione/hash esatti, file
di licenza, notice, release manifest, SBOM e verifica offline. I download silenziosi a runtime
restano vietati.

Il record
[`tesseract-5.5.3.json`](../../packaging/ocr/tesseract-5.5.3.json) contiene matrice piattaforme,
provenienza dei pack di riferimento, budget dimensionali e gate di redistribuzione.

## Prossimo slice

`0.9/S02` potrà implementare preparazione limitata delle pagine PDF/immagine, isolamento del
processo Tesseract, persistenza degli artefatti derivati e integrazione nei document bundle contro
questo contratto esatto. Non è attivo e non ha ancora issue, branch o owner PR.

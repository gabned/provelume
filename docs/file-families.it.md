# Profili limitati di tabelle e archivi

Perceptio aggiunge esattamente tre profili locali e versionati di livello superiore: celle CSV
UTF-8/UTF-8-BOM, fogli e celle XLSX memorizzate nella cache, e membri ZIP. Gli Original esatti
restano autorevoli. I profili sono derivati, vincolati da checksum, rimovibili e ricostruibili; non
modificano mai sorgenti o record canonici.

## Matrice di supporto

| Profilo | Parser | Evidenza di livello superiore | Limite chiuso |
| --- | --- | --- | --- |
| `perceptio-csv-cell-v1` | Python 3.12 `csv`, PSF-2.0 | delimitatore, valori visualizzati e ancore esatte riga/colonna/cella | solo UTF-8; 16 MiB, 5.000 righe, 200 colonne e 100.000 celle |
| `perceptio-xlsx-sheet-cell-v1` | Python 3.12 `zipfile` + `xml.etree.ElementTree`, PSF-2.0 | fogli in ordine workbook, valori cache visualizzati, presenza formula e ancore esatte foglio/cella | input 64 MiB; package/XML/fogli/righe/celle limitati; nessuna relazione esterna, macro o contenuto attivo incorporato |
| `perceptio-zip-member-v1` | Python 3.12 `zipfile`, PSF-2.0 | percorso normalizzato, SHA-256, tipo media fisso, dimensioni, rapporto e ancora esatta del membro | membri/byte/rapporto/tempo limitati; niente cifratura, symlink, percorso insicuro, espansione annidata o estrazione host |

Le codifiche non supportate e le celle XLSX con sola formula fanno fallire l'operazione derivata
richiesta. Anche membri insicuri, cifrati, corrotti, duplicati/in collisione o eccessivi falliscono
in modo chiuso. La conservazione di un Original già acquisito resta indipendente dal profilo.

## Operazione locale

Servizio e CLI espongono azioni esplicite di coda, esecuzione, annullamento, nuovo tentativo,
rimozione e ricostruzione. Per esempio:

```console
provelume file-family-queue INSTANCE VERSION_ID perceptio-csv-cell-v1
provelume file-family-run INSTANCE JOB_ID
provelume file-family-profiles INSTANCE
```

API HTTP e pagina Browser `/file-families` sono di sola lettura. Ogni cella o membro visualizzato
collega la propria ancora tipizzata completa. I valori sono sottoposti a escape automatico e gli
output JSON sono serviti con `nosniff` e policy restrittiva senza script né oggetti. Testo delle formule, macro,
script, HTML e allegati non vengono mai eseguiti. Il parsing non usa rete, scoperta plugin, download
runtime o inferenza remota.

DOCX/presentazioni, TSV/ODS/JSONL/Parquet, notebook, EML/PIM, HTML/MHTML/WARC/WACZ, TAR/GZ/7Z,
geospaziali e amministrativi firmati restano fuori da S06 e mantengono il supporto veritiero
esistente o la destinazione roadmap successiva.

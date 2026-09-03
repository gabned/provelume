# Pilot integrato Perceptio

Perceptio è la superficie integrata, locale e di sola lettura per gli esatti profili foto, audio,
video e CSV/XLSX/ZIP pubblicati nella `0.10.0`. Identità del pacchetto, runtime incorporato e
prodotto Windows sono `0.10.0`. Un normale checkout sorgente riporta `candidate`. Una build con
identità incorporata esattamente `0.10.0` / `v0.10.0` riporta soltanto
`official_metadata_present` e `external_release_verification_required`: i metadati sono descrittivi
e non autenticano mai da soli pubblicazione o integrità dell’installazione.

## Un unico percorso dell’evidenza

Apri **Pilot Perceptio** nel Browser oppure esegui:

```bash
provelume perceptio-status ISTANZA
provelume perceptio-status ISTANZA --version-id VERSION_ID --limit 100
provelume perceptio-representation ISTANZA REPRESENTATION_ID
```

Servizio, CLI, `GET /api/v1/perceptio` e pagina `/perceptio` usano la stessa proiezione. Ogni
risultato affianca Versione e rappresentazione esatte a superficie di galleria/player/evidenza,
disponibilità, supporto, componente/adattatore, avvisi d’incertezza, annotazioni di correzione
reversibili, ancore esatte e output derivati. Anche dettaglio e ancore sono solo GET: nessuna rotta
integrata avvia lavori, applica correzioni, rimuove output o modifica una Source.

Le letture di stato usano dichiarazioni incluse nel pacchetto ed evidenze di profili/lavori già
registrate. Non calcolano hash, non eseguono e non sondano codec, motori, binari o modelli
opzionali; i comandi espliciti delle singole famiglie restano l’autorità per un nuovo probe locale.

## Stati, accessibilità e contenuti ostili

Il contratto distingue stati riuscito, vuoto, caricamento, degradato, indisponibile, interrotto e
ripristino. La vista EN/IT usa landmark, titoli, tabelle native, liste di definizioni, collegamenti e
controlli di espansione; eredita skip link, focus visibile, reflow, colori forzati e movimento
ridotto. Il significato non dipende soltanto dal colore.

Le letture non usano la rete e non scrivono in Originali, record canonici, dati provider o file
sorgente. Il GPS resta escluso dall’export predefinito. Testo, HTML, formule, script, prompt,
elementi d’archivio e media incorporati sono mostrati come dati inerti. Restano autoritativi i
limiti per profilo su byte, quantità, durata, pixel, espansione, processo, memoria, disco e tempo.

## Ripristino e pubblicazione

Rimozione/ricostruzione delle rappresentazioni, backup/ripristino e trasferimento portabile
mantengono i contratti esistenti. La qualifica di release prova inoltre installazione pulita,
upgrade dalla `0.9.0`, rollback e conservazione dei dati alla disinstallazione. Perceptio diventa
pubblicato soltanto quando PR di versione, commit `main`, verifica offline, tag immutabile
`v0.10.0` e asset canonici coincidono esternamente. Le build di sviluppo restano candidate; anche
gli esatti metadati release incorporati richiedono la verifica separata di installazione e bundle.

Vedi la [qualifica release 0.10.0](qualification/0.10.0.md), il
[record di release](releases/0.10.0.md) e il [contratto privacy](privacy-network.md).

# Pilot integrato Perceptio

Perceptio è la superficie integrata, locale e di sola lettura per gli esatti profili foto, audio,
video e CSV/XLSX/ZIP già ammessi dal piano `0.10.0`. Durante S07 resta un candidato non pubblicato:
la presenza della pagina o dell’API non rende disponibile `0.10.0`. Identità del pacchetto, runtime
incorporato e prodotto Windows restano `0.9.0` fino al confine di release separato.

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
disponibile soltanto quando PR di versione, commit `main`, verifica offline, tag immutabile
`v0.10.0` e asset canonici coincidono.

Vedi la [mappa di qualifica S07](qualification/perceptio-s07.md), il
[piano di supporto](releases/0.10.0.md) e il [contratto privacy](privacy-network.md).

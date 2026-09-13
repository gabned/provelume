# Catalogo dei componenti

La pagina locale **Componenti** e `GET /api/v1/components` spiegano quali parti del runtime
effettivo di Provelume sono installate, mancanti o ancora non verificate. Lo stesso JSON è
disponibile con:

```bash
provelume component-inventory
```

Ogni voce indica categoria, scopo, relazione di dipendenza, modalità di distribuzione e
aggiornamento, licenza/avvisi, contratto di versione, versione effettiva e stato dell'evidenza.
L'inventario Python segue tutte le dipendenze runtime installate di Provelume, comprese quelle
transitive presenti ed esclusi gli extra di sviluppo.
`installed` significa soltanto che i metadati locali del runtime o della distribuzione rispettano
il contratto dichiarato: non è una garanzia di sicurezza. `ahead`, `incompatible`, `eol`,
`missing` e `unverified` restano stati distinti.

L'inventario non esegue strumenti opzionali e non esplora le cartelle dei modelli. La presenza di
un eseguibile è indicata senza mostrarne il percorso; modelli e pacchetti lingua richiedono
evidenze esplicite. Credenziali, percorsi privati e contenuti dell'Istanza non sono inclusi.

Lo schema 2 aggiunge `ui_asset` alle sette categorie esistenti. La voce `ui.lucide`
descrive le 18 icone incluse nel pacchetto Provelume, versione 1.45.0, con la licenza
upstream completa `ISC AND MIT`. Lo stato installato richiede gli hash esatti del
manifest, degli SVG e della licenza nelle risorse del pacchetto. Un file mancante o
alterato resta mancante o non verificato. Non viene consultato alcun servizio di
icone, eseguibile o catalogo remoto. [ADR 0028](adr/0028-cura-icons-and-provenance.md)
registra il pin e il percorso di aggiornamento.

## Confronto con lo SBOM di release

Un operatore locale può confrontare uno SBOM CycloneDX scaricato o assemblato:

```bash
provelume component-inventory --release-sbom /percorso/locale/attendibile/bom.cdx.json
```

Il file è letto localmente entro limiti di byte e componenti. Il comando non contatta cataloghi,
servizi advisory, provider o host di modelli e non installa né aggiorna nulla. Senza questa
evidenza esplicita il confronto di release è correttamente `unavailable`. Versione più recente e
stato di sicurezza restano `not_checked` e `unverified` finché non sarà qualificata una capacità
di rete separata ed esplicita.

Lo SBOM di release comprende lo stesso sottoinsieme installato prima di generarne
l'impronta. La sola versione non basta: devono coincidere anche commit e hash del
sottoinsieme e della licenza. Un sottoinsieme alterato con la stessa versione risulta
non corrispondente.

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

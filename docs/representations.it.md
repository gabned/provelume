# Rappresentazioni e supporto — guida utente

La pagina Rappresentazioni spiega due cose diverse:

1. cosa Provelume può fare con un profilo di contenuto su questo computer;
2. quali nuovi bundle derivati universali sono presenti e validi nella Instance.

Aprire la pagina, chiamare l'API o eseguire i comandi di ispezione è un'operazione offline e in
sola lettura. Non analizza un provider, non avvia OCR, non crea anteprime, non ripara bundle e non
aggiorna componenti.

## Leggere separatamente i sei livelli

- **Preserve** significa conservare i byte esatti con il relativo checksum.
- **Inspect** significa leggere fatti strutturali entro limiti chiusi.
- **Extract** significa produrre una rappresentazione derivata, per esempio testo.
- **Preview** significa disporre di una vista locale inerte.
- **Local enrich** richiede il componente locale e la configurazione indicati.
- **AI enrich** non è disponibile in S01; non esiste alcun percorso AI.

Preserve disponibile non promette nessun altro livello e non rende il contenuto ricercabile.
`declared_state` indica ciò che il profilo pubblico consente. `effective_state` indica ciò che è
disponibile ora. `reason` e `missing_component` spiegano un livello degradato o non disponibile
con un valore chiuso, senza deduzioni.

## Ispezione locale

```bash
provelume representation-support INSTANCE
provelume representation-support INSTANCE --profile-id lectio-local-ocr-v1
provelume representations INSTANCE
provelume representation INSTANCE REPRESENTATION_ID
```

Gli stessi dati sono disponibili in `/representations`, `/api/v1/representations/support`,
`/api/v1/representations` e `/api/v1/representations/{representation_id}` sul servizio locale
vincolato al loopback.

## Original e compatibilità

Le rappresentazioni universali sono stato derivato rimovibile. Rimozione e rebuild non modificano
Original, conoscenza canonica o dati provider. Una nuova recipe crea una rappresentazione distinta
e conserva nella storia l'identità precedente.

Estrazione documentale Lectio, OCR locale, email, Google in sola lettura, SRT/WebVTT e finding
cross-source compaiono come viste di compatibilità. I byte memorizzati non vengono convertiti. Le
Instance schema-2 esistenti non richiedono migrazione e nessun file Markdown viene creato accanto a
un Original.

Backup, restore e trasferimento portabile includono questo stato derivato durevole e lo validano in
profondità. Output corrotti, mancanti o non corrispondenti vengono rifiutati e non sono mai promossi
a conoscenza canonica.

# Adapter Google Gmail e Drive in sola lettura

`0.9/S04` aggiunge un adapter Google sostituibile dietro i contratti provider-neutral di
connector, Source, email e documento. È sviluppo non pubblicato e mantiene package, runtime e
identità embedded a `0.8.0`.

## Autorità e isolamento

Ogni identità Google corrisponde a un `ConnectorInstance`. Gmail e Drive sono capability
indipendenti, ciascuna con consenso esplicito e un solo scope:

| Capability | Scope | Mutazioni provider |
|---|---|---|
| Gmail | `https://www.googleapis.com/auth/gmail.readonly` | nessuna |
| Drive | `https://www.googleapis.com/auth/drive.readonly` | nessuna |

L’autorizzazione conserva soltanto `{kind, name}` di un riferimento environment o system keyring.
Access token, refresh token, client secret e header Authorization non sono mai serializzati. La
revoca elimina il riferimento e disabilita solo la capability interessata. La riautorizzazione
incrementa la revisione della capability e non la riabilita silenziosamente.

Ogni selezione di mailbox/label o file/cartella è una Source connector separata. La Source possiede
schedule, lifecycle, cursore, fingerprint delle pagine e health. Non esiste merge cross-Source.
API e Browser redigono selettori e cursori raw in conteggio/hash o sola presenza.

## Disclosure di rete

Il gate effettivo richiede contemporaneamente:

1. `network.external_access` abilitato sull’Instance;
2. ConnectorInstance abilitato in modalità esplicita;
3. capability Gmail o Drive autorizzata e abilitata;
4. Source specifica abilitata;
5. allowlist del connector uguale all’insieme chiuso di origin Google.

La preview REST accetta solo HTTPS e disabilita i redirect. Gli origin ammessi sono
`accounts.google.com`, `oauth2.googleapis.com`, `gmail.googleapis.com` e
`www.googleapis.com`. L’acquisizione usa soltanto GET bounded. I percorsi disabilitati falliscono
prima della risoluzione della credenziale e prima dell’apertura di un socket. Gli errori espongono
codici chiusi, non URL, query, header o contenuto.

## Acquisizione Gmail

La selezione Gmail è esplicita: mailbox autorizzata `me` o uno o più identificatori di label. Ogni
pagina è bounded e ogni messaggio viene letto come Gmail `format=raw`. I byte RFC 822 decodificati
entrano invariati nella pipeline S03:

- Original esatto del messaggio e Original figli esatti degli allegati accettati;
- Document/Version/Acquisition provider-neutral ed evidenze email S03;
- rappresentazione email rimovibile e inerte;
- sola idoneità OCR degli allegati, con `execution_requested=false` e
  `execution_started=false`.

ID messaggio Gmail, history/revision ID, thread ID e label diventano osservazioni SHA-256 con
namespace e confinate alla Source. Message-ID dichiarato, indirizzi e date restano osservazioni S03
non autorevoli. Byte uguali possono essere deduplicati crittograficamente, ma Source e osservazioni
provider separate restano separate.

Invio, bozze, eliminazione, modifica label e write-back non hanno comandi, metodi API o operazioni
dell’adapter.

## Acquisizione Drive

La selezione Drive è un insieme esplicito di identificatori di file o cartelle. I file binari usano
`alt=media` e i byte della risposta diventano l’Original esatto. I formati Google-native supportati
usano un solo export bounded:

| Formato sorgente | Formato export |
|---|---|
| Google Docs | PDF |
| Google Sheets | XLSX |
| Google Slides | PDF |

Dopo la lettura del contenuto i metadati vengono riletti. Una revisione o un MIME type cambiato
produce `google_remote_mutation` e non promuove nulla. L’evidenza di revisione registra riferimenti
file/revisione hashati, Document/Version provider-neutral, acquisition, formati origine/export,
checksum, dimensione, tempi osservato/accettato e Original exact-byte. I formati Google-native non
supportati falliscono visibilmente invece di scegliere un export implicito.

Update, delete, share, permessi e write-back Drive sono assenti. Un binario senza estrattore locale
rimane un Original verificato con rappresentazione leggibile non disponibile; non avvia OCR né
fallback remoto.

## Esecuzione durevole

`google.intake` è un job Vigilia confinato alla Source. La richiesta lega fingerprint di
Source/capability, revisioni capability/cursore, scope esatto, allowlist, hash della selezione e
limiti chiusi. Non contiene nomi di riferimenti credenziale, selettori raw, cursori provider o
contenuto privato.

I limiti predefiniti sono 32 pagine, 100 item per pagina, 500 item, 32 MiB per item, 256 MiB per
run, 4 MiB di JSON metadati, 100 errori item, 256 fingerprint pagina e timeout richiesta di 30
secondi. Tutti i massimali sono chiusi e validati.

Il work journal contiene solo identità/checksum item, dimensione, ID canonico, stato ed errore
chiuso. I cursori raw rimangono in `state/google-adapters/sources/<source>.json`; le superfici
pubbliche espongono soltanto la presenza. Un mismatch del fingerprint pagina invalida il cursore e
richiede resync visibile. Rate limit e failure transitori usano retry bounded dello scheduler. La
scadenza OAuth porta solo la capability interessata a `reauthorization_required`. La promozione
atomica per item e il recovery delle transazioni rendono idempotente il replay del lease.

## Superfici e qualificazione

Service e comandi CLI `google-*` espongono controlli per identità, capability, Source, schedule,
cursore, job, revoca ed evidenze. `/google` offre controlli loopback protetti da CSRF in inglese e
italiano. `/api/v1/google/*` è read-only; le mutazioni restituiscono 405.

La CI pubblica usa pagine sintetiche deterministiche e non richiede credenziali. L’implementazione
REST inclusa è una seam preview, non qualificazione provider reale. Finché uno smoke permanente e
autorizzato non prova un head esatto contro Google, l’evidenza packaging dichiara
`local-conformance-preview` e `real_google_qualified=false`.

Vedi [ADR 0017](../adr/0017-google-readonly-adapters.md), la
[guida inglese](google-readonly-adapters.md) e la [guida API](../api.md).

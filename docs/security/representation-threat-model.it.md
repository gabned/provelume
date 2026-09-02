# Delta del threat model per le rappresentazioni universali

Questo delta si applica solo a `0.10/S01`. Restano validi i confini di sicurezza locali,
clean-room, Original immutabili e servizio vincolato al loopback.

| Minaccia | Controllo S01 | Confine residuo |
| --- | --- | --- |
| Un tipo conservato viene presentato come estraibile o ricercabile | Sei righe indipendenti; Preserve non concede operazioni superiori | Ogni profilo futuro deve qualificare separatamente le operazioni superiori |
| Path traversal o sostituzione di output tra bundle | Percorsi relativi normalizzati e compatibili con Windows, vincolo alla radice esatta della rappresentazione e risoluzione sicura nella Instance | L'integrità del filesystem host resta responsabilità dell'operatore |
| Collisione tra maiuscole/minuscole o file/directory cambia il significato portabile | Set ordinato e univoco, rifiuto delle collisioni case-folded e di tipo nodo | Il comportamento Unicode fuori dalle regole portabili chiuse non è supportato |
| Esaurimento tramite decompressione o output derivato | Limiti chiusi per conteggio, file, byte totali e rapporto di espansione | Decoder futuri richiedono limiti pixel/durata/processo nella propria slice |
| Bundle/output alterato viene mostrato o importato | Schema rigoroso, fingerprint di recipe/output/rappresentazione e deep validation di hash/dimensione | S01 prova coerenza interna, non autentica un publisher esterno |
| Un anchor esce dalla propria evidenza | Ogni anchor ripete ID esatti di Version e rappresentazione; target non validi falliscono chiusi | I tipi di anchor riservati non dichiarano supporto a formati |
| Una correzione sovrascrive l'autorità | Correzioni come annotazioni reversibili vincolate da checksum sullo stato derivato | Intenzione utente e correttezza semantica restano decisioni da revisionare |
| La rimozione distrugge la storia | Una ricevuta derivata conserva fingerprint e provenance esatte del bundle | Il rebuild richiede ancora recipe/componente bloccati e byte rigenerati |
| Una migrazione legacy corrompe dati Lectio | Mapping di compatibilità incluso nel pacchetto e solo come vista; nessuna migrazione eager o campo canonico | Lo stato legacy non valido resta gestito dal contratto originario |
| L'ispezione delle capacità avvia rete o esecuzione | Registry incluso nel pacchetto più evidenza locale; le letture dichiarano `network_used: false` | Installare un componente opzionale è un'azione esterna esplicita dell'operatore |
| Un percorso AI compare tramite “enrich” generico | `ai_enrich` è forzato a non disponibile con `not_implemented`; invariante del bundle `ai_used: false` | Una release AI futura richiede threat model e autorizzazione separati |

Il Browser mostra solo identificatori, stati, motivi chiusi, nomi dei componenti e conteggi. Non
renderizza output della rappresentazione, markup attivo o contenuto provider. Le letture di
service, CLI e API non creano, riparano, rimuovono o ricostruiscono rappresentazioni.

Backup e import portabile validano l'intera Instance di staging prima del commit. Un finding sulla
rappresentazione blocca l'installazione; failure, cancellazioni e timeout non diventano successi.

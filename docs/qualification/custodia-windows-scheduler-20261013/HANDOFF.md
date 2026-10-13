# v0.12.1 pubblicata; residuo documentale #348

La release v0.12.1 Custodia Preview, ID 410870418, è già pubblica, non draft, prerelease/Preview. Il tag e il main restano cd7dc64f3ffb2a17689018b3350f0e1c073abdd4. Il workflow publisher originale 38282337063 è la prova di consegna; il download corrente di Setup, receipt e readiness coincide con gli SHA-256 originali. Nessuna nuova pubblicazione, tag, receipt, kit o readiness.

Owner #348: product/release-0.12.1-delivery-record, PRODUCT / REPOSITORY_POLICY, PR-local legacy. Head e750c0531a4be22f304ab47929db406213578ebd. Protocollo 1.5.1/source 1a11fe76712ee65ca2160d2ae3789330946a57f2, 97 file verificati, v2 differita. Il FAIL originale 38289564204 attempt 1 resta Windows Family 25 Model 1, 26/27, en04/run2 5.797 > 5 secondi; il gate legacy su tutti i latest workflow applicabili impedisce il merge. Preflight BLOCKED precedenti e BOUND storica MISSING restano nell'audit e nel materiale precedente, non riscritti né ricostruiti.

Owner diagnostico separato: product/custodia-windows-phase-diagnosis. Terza raccolta, run 38411371368 attempt 1, head 6018b88d3c886518a80216c54aed1fff594ed5e1: profilazione ETW limitata a tre finestre en01–en04, QPC e tempi CPU/request/PID. Profile kernel: CSwitch, ReadyThread, SampledProfile, DiskIO, DiskIOInit, HardFaults. Sono esclusi ProcessThread, Loader e FileIO; esportazione numerica senza comandi, nomi file, percorsi o contenuto della memoria. Nessuna modifica Core o qualificatore. Le tracce raw ETL e gli artifact ZIP originali sono conservati.

Host della terza raccolta: AMD Family 25 Model 1 Stepping 1, diverso host disposable rispetto all'originale. Report OBSERVED, 60 sample, worker absent. DIAGNOSTIC_ONLY / NOT_EVALUATED. ETW: zero eventi persi, intervalli nativi interamente coperti, nessuna discontinuità di context switch. I byte delle tre ETL estratte coincidono con size/hash osservati dal recorder.

| en04 | First wall | Prefill QPC | CPU running ETW aggregata | Ready-wait worker aggregata |
| --- | ---: | ---: | ---: | ---: |
| run0 | 2.407 s | 1.3153041 s | 2.6215087 s | 0.0077689 s |
| run1 | 2.469 s | 1.3747658 s | 2.6331666 s | 0.1151941 s |
| run2 | 2.438 s | 1.3399803 s | 2.6392004 s | 0.0396236 s |

Nelle nuove finestre en04 il worker usa due thread di calcolo e il kernel osserva brevi occupazioni dei suoi core da parte di altri thread. I tempi ready e le occupazioni si corrispondono nella prova nuova; l'attesa aggregata dei thread non è una quota additiva della latenza wall. Nessun I/O/hard-fault attribuito ai thread worker negli intervalli di decode osservati. La frequenza dinamica CPU e la contesa sul physical host/hypervisor non sono osservate. Non si promuovono questi limiti a prova di assenza di ogni costo.

Il picco originale non è riprodotto. Nessuna traccia scheduler del suo host è disponibile: la causa tecnica specifica di 5.797 s resta NON_DIMOSTRATA. Non è dimostrato un difetto runtime correggibile, pertanto nessuna correzione runtime o nuova qualifica originale. Non eseguire un altro tentativo invariato per scegliere un verde. Per una futura qualifica occorre prima una causa dimostrata e una modifica pertinente; un eventuale difetto runtime richiede una PR/owner separati e la propria review/qualifica. Solo poi riconciliare #348 e, con tutti i gate soddisfatti, eseguire preflight fresco, normale expected-head merge, parent/tree e post-merge reali.

La prossima azione sul residuo è una prova discriminante durante un effettivo rallentamento, con frequenza/cicli e contesto host/VM se disponibile: le tre nuove osservazioni senza picco non ricostruiscono l'evento storico. Questa lacuna non impedisce di scaricare o usare la Preview già consegnata.

Kit completo originale 47177228 B oltre 32 MiB, non scaricato qui; prova publisher distinta. Verifiche umane/hardware non attestate, Windows 10 22H2 BLOCKED e cancellation diagnostica NOT_OBSERVED conservate. Sito provelume.com separato dai gate Core; 0.12.0 immutabile e 0.13.0 Iudicium.

Modello/effort del runtime UNKNOWN; mantenerli se disponibili. Carico residuo HIGH, incertezza: evento non riproducibile e assenza della telemetry originale. Prompt: Riprendi #348 owner product/release-0.12.1-delivery-record, head e750c0531a4be22f304ab47929db406213578ebd, base/main cd7dc64f3ffb2a17689018b3350f0e1c073abdd4, pin 1.5.1/source 1a11fe76712ee65ca2160d2ae3789330946a57f2 e v2 differita. La release è già pubblica. Usa gli audit e le tre diagnosi conservate sul branch separato per verificare una causa del rallentamento prima di correzioni o nuove qualifiche; conserva FAIL, preflight BLOCKED e BOUND MISSING. Non ricreare la release. Gate e merge rimangono condizionati alle verifiche reali.


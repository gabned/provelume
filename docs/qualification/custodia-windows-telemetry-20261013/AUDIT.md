# Verifica delle capacità Windows e blocco #348

Ripresa dalla diagnosi/audit issuecomment-6147912698, 13 ottobre 2026.
Release v0.12.1 ID 410870418 già pubblicata; nessuna release, tag, receipt,
kit o readiness ricreati. #348 owner product/release-0.12.1-delivery-record,
head e750c0531a4be22f304ab47929db406213578ebd; base/main/tag
cd7dc64f3ffb2a17689018b3350f0e1c073abdd4. PRODUCT / REPOSITORY_POLICY,
PR-local legacy, 97 file Protocol source 1a11fe76712ee65ca2160d2ae3789330946a57f2
BYTES_VERIFIED, v2 differita. AGENTS locale e blob GitHub accettato coincidono.
Selettore storico 1.4.9 verificato nel compat/legacy della distribuzione adottata.
Il tentativo iniziale col manifest storico 1.4.7 locale ha rifiutato AGENTS
per integrità ed è conservato; nessuna modifica di manifest o gate per superarlo.

Il run originale 38289564204 attempt 1/job Windows 114946100843 è riletto e
conservato integralmente: Family 25 Model 1, 26/27, en04/run2 first-wall
5.796999999999912 > 5 s; native first 4.046999999999912 e residuo 1.750 s.
Entrambi i report prima/dopo WFP restano FAIL. Nessun dato di frequenza effettiva,
istruzioni/PMC o contesa host del vecchio campione è presente. Le tre diagnosi
precedenti restano DIAGNOSTIC_ONLY / NOT_EVALUATED e non dimostrano quel picco.

## Nuove sonde, senza modello o gate prodotto

1. 38424381686 attempt 1, head 26e59bcffd4b9584ca039e2929ac993aed439e4f,
   guest AMD Family 25 Model 17: inventario PDH/WPR, contabilità thread e
   registrazione provider power. Artifact 11827712403, ZIP 4106 B,
   SHA-256 76d68c4d206885271a954a244452e34d98bf66f01a6eaddf4e7e78b5f04769d4.
2. 38424771445 attempt 1, head c2ee473980cda5e1cf38c88247d2efd47f9ff2af,
   guest Intel Family 6 Model 207: campionamento dei nuovi canali Actual
   Frequency/Hyper-V scoperti nell'inventario. Artifact 11828142584, ZIP 5036 B,
   SHA-256 e42ad9091435d5775b91cb700ca53a87929a341093ba5f0773b192b89b4b258e.

Entrambi i run sono SUCCESS come esecuzione delle sonde; qualifica prodotto
NOT_EVALUATED. Download via trasporto supportato, hash ZIP API e tutti i membri
verificati. La seconda sonda cambia i canali osservati: non è un retry per
qualificare un candidato né una diagnosi Core ripetuta senza nuovi input.

Actual Frequency è disponibile come valore PDH del secondo guest (status 0,
3039.7565–3051.8952 MHz). Non è telemetria indipendente dell'host originale.
WPR elenca solo Timer su entrambi i nuovi guest: PMC hardware non esposti in
questa interfaccia. QueryThreadCycleTime è contabilità Windows, senza retired
instructions/IPC. Le ETL power, pur registrate e decodificate, contengono zero
eventi del provider CPU; nessuna disponibilità dinamica dedotta dal solo successo.
CPU Wait Time Per Dispatch UNAVAILABLE; i contatori Hyper-V di utilizzo visibili
non attestano identità o contesa dell'host fisico.

In seguito al canale osservato è preparato il wrapper e il protocollo in
PREPARED-PROOF.md. Run 38425341909 SUCCESS verifica solo il parser PowerShell
del wrapper, non ne attesta comportamento runtime/trasparenza o risultato.
La prova discriminante con modello resta PREPARED / NOT_EXECUTED.
Non è dimostrato un difetto Core: nessuna correzione o PR runtime.

## Blocco preciso e continuità

#348 resta OPEN / BLOCKED: il FAIL originale è ancora il latest tentativo
applicabile del workflow CPU nel contratto legacy. I 19 run sull'head riletto
sono distinti: 14 source PR (13 SUCCESS e quel FAIL), cinque target SUCCESS.
Nessun nuovo preflight o merge. Vecchi preflight BLOCKED e BOUND storica MISSING
restano preservati e referenziati, senza ricostruire file storici assenti.
Binding corrente originale del commento 6129996130 è distinto dalla BOUND
storica mancante. Evidenze precedenti e archivi dei commit 7053227/bb5e688/
254a852 restano intatti; questa raccolta si aggiunge e non li sostituisce.

Kit completo originale 47177228 B oltre 32 MiB, prova publisher distinta:
nessun download locale completo attestato. Verifiche umane/hardware non
attestate; Windows 10 22H2 BLOCKED, cancellation NOT_OBSERVED. Sito separato
dai gate Core; 0.12.0 immutabile, 0.13.0 Iudicium.

Prossimo passo tecnicamente preparato: una singola osservazione prospettica
con il wrapper, previa capacità valida sul guest effettivo; non cambia lo stato
di #348. La causa dell'evento storico resta NON_DIMOSTRATA e i suoi canali
originali MISSING. Modello/effort operativo UNKNOWN; lavoro residuo HIGH per
l'assenza della telemetria storica e l'evento non riprodotto.

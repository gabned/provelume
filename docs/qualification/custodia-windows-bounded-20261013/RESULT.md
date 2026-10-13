# Tentativo delimitato concluso; #348 OPEN / BLOCKED

Owner diagnostico `product/custodia-windows-phase-diagnosis`, PRODUCT / REPOSITORY_POLICY,
PR-local legacy. Pin 1.5.1/source `1a11fe76712ee65ca2160d2ae3789330946a57f2`, 97 file
BYTES_VERIFIED; v2 differita. La selezione legacy verificata è 1.4.9/GIT/START,
manifest canonical digest `76afc7557cdf23bcb818510dce630346d3a17c7c2057da821873732ff712602b`.
Due chiamate preliminari avevano passato il digest dei byte anziché quello JSON
canonico: rifiutate, senza cambiare manifest, pin o autorità. `main` riconciliato:
`cd7dc64f3ffb2a17689018b3350f0e1c073abdd4`.

## Verifica dell'osservatore prima del modello

Il wrapper preparato è stato reso verificabile su fixture con job PowerShell reali.
Registra fine richiesta, errori e stop forzato separatamente, controlla campioni,
clock e canali, rimuove il job anche sui fallimenti e rifiuta output già esistenti
prima di scriverli. Nessun file Core, soglia, affinity, priorità, hardware di
riferimento o qualificatore prodotto modificato.

Run sintetico `38433508859` / head `a77998dd3c83349b9c955708c9461223408c39b9`
ha trovato perdita dei millisecondi riconvertendo un DateTime deserializzato da
PowerShell. Esito originale FAILURE conservato in `synthetic-failure.zip` e log;
modello e raccolta reale SKIPPED. Correzione limitata all'osservatore diagnostico.
Sul successivo head `cdf85c0650850a50545d1d4d1a61fdde26fc8929` sono passati 11 casi:
normal, probe-invalid, startup-error, early-end, late-error, hung, invalid-counter,
clock-inversion, harness-error, missing-terminal, fresh-directory-preservation.
Questa è validazione sintetica, non trasparenza temporale assoluta del wrapper.

## Unica raccolta predefinita

[Run 38433671494 attempt 1](https://github.com/gabned/provelume/actions/runs/38433671494),
Windows job `115422041431`, head `cdf85c0650850a50545d1d4d1a61fdde26fc8929`:
SUCCESS come esecuzione diagnostica, **DIAGNOSTIC_ONLY / NOT_EVALUATED**.
Tre finestre en01–en04 fisse nello stesso harness/corpus e bootstrap locked.
Actual Frequency riconfermata prima del modello sul guest effettivo **AMD Family
25 Model 1**, Windows Server 2025, Python 3.12.10, 4 CPU logiche. È un NUOVO guest:
la stessa family/model non identifica l'host storico e non trasferisce telemetria.

235 campioni PDH, status validi; nessuna inversione/gap oltre il controllo
predefinito dell'osservatore. QPC Windows 10 MHz e Python QueryPerformanceCounter
verificati con letture racchiuse; dispersione degli anchor QPC/UTC 1.157 ms.
I timestamp PDH vengono collocati dagli anchor, non dal QPC dopo la raccolta.
ETW: tutti gli intervalli native decode coperti, zero eventi persi, zero
interruzioni della continuità context-switch. ETL raw corrispondenti agli hash
registrati. Worker assente a fine harness; sampler terminato con STOP_REQUESTED,
nessun errore/stop forzato, job rimosso. Nessuna impostazione persistente cambiata.

| en04 | First wall | Decode QPC | Running ETW aggregato | Ready ETW aggregato | Campioni PDH nel decode |
| --- | ---: | ---: | ---: | ---: | ---: |
| run0 | 2.531 s | 1.423126 s | 2.720685 s | 0.124152 s | 2 |
| run1 | 2.484 s | 1.360504 s | 2.643357 s | 0.076402 s | 1 |
| run2 | 2.469 s | 1.363502 s | 2.643156 s | 0.082435 s | 2 |

Actual Frequency nei decode: circa 3242.37–3243.28 MHz riportati dal guest.
La seconda finestra NON soddisfa il minimo di due campioni per discriminare
la frequenza durante un decode rallentato. Il campionamento a 1 s non attribuisce
ritardi di pochi ms. I tempi aggregati dei thread non si sommano alla latenza wall;
admission/hash/load, prefill, ready/running e IPC/dequeue restano distinti nei
JSON di fase e nei file request/PID. Nessun I/O/hard fault osservato attribuito ai
thread worker negli intervalli decode; non è una prova di assenza di tutti i costi.
PMC hardware e contesa fisica restano UNOBSERVED.

Nessuno dei 60 sample ha first-wall >5 s. Il picco originale NON è riprodotto.
Causa **NON_DIMOSTRATA**, nessun difetto runtime dimostrato, **nessuna correzione**.
Il tentativo finisce qui: nessun retry invariato, altra campagna o modifica al gate.

## #348 e invarianti

#348 owner `product/release-0.12.1-delivery-record`, head
`e750c0531a4be22f304ab47929db406213578ebd`: OPEN / BLOCKED. Inventario riletto:
19 run (14 source PR, di cui il FAIL `38289564204` attempt 1; cinque target SUCCESS).
Originale Windows Family 25 Model 1, 26/27, en04/run2 5.797 >5 s conservato come FAIL.
La nuova raccolta non lo qualifica né ne dimostra la causa. Nessun nuovo preflight
inutile o merge tentato; preflight precedenti BLOCKED, BOUND storica MISSING.
Parent/tree e post-merge non eseguiti, non PASS.

Release v0.12.1 ID 410870418 già pubblicata, 26 asset; nulla ricreato. Kit originale
47177228 B >32 MiB, download completo non attestato qui. Verifiche umane/hardware
non attestate; Windows 10 22H2 BLOCKED, cancellation NOT_OBSERVED. Sito separato;
0.12.0 immutabile. La richiesta del maintainer autorizza ora **0.13.0 Iudicium**
indipendentemente dal residuo #348; il suo sviluppo non assorbe quel residuo e
non autorizza pubblicazione.

## Materiale e ripristino

`evidence.zip`: 7,178,140 byte, SHA-256
`a18d22b5423e866354e217e185451638602d8848f85a9b9eaf7b5a73fe615ecd`,
102 membri. Include quattro ZIP artifact originali, estratti raw ETL/PDH/QPC,
fixture sintetiche, primo fallimento, log, metadata GitHub, analisi e inventario.
Tutti i quattro digest ZIP coincidono con GitHub e ogni membro estratto è stato
confrontato byte per byte; ogni ETL coincide con il recorder. La verifica di
scaricamento/ripristino indipendente dal branch è registrata in RESTORE.json.

Ripristinare in una directory nuova con zipfile, verificare SHA e `inventory.json`;
eseguire `python analyze_frequency.py restored analyze_scheduler.py` dalla radice
estratta. Il reducer scheduler è quello preesistente, incluso senza modifiche.
Rileggere GitHub prima di qualsiasi futura azione. La prossima azione autorizzata
è S01 Iudicium sul main riconciliato, con issue/owner/PR distinti e gate propri.

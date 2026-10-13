# Prova preparata, non eseguita

Owner `product/custodia-windows-phase-diagnosis`. PRODUCT / REPOSITORY_POLICY,
PR-local legacy, pin 1.5.1/source 1a11fe76712ee65ca2160d2ae3789330946a57f2;
v2 differita. La preparazione non qualifica #348 e non cambia Core o soglie.

## Canale disponibile e limiti

La sonda 38424771445/c2ee473 ha misurato Actual Frequency con tutti gli status
PDH zero, 3039.7565–3051.8952 MHz, su guest Intel Family 6 Model 207. Sono valori
riportati dal guest, non una misura indipendente dell'host fisico. Processor
Frequency/CIM indicano invece 2300 MHz nominali. Nel precedente guest AMD Family
25 Model 17 la prima sonda aveva enumerato Actual Frequency senza campionarla:
non dichiarare che il suo valore sia stato verificato. Entrambi i guest sono
distinti dal Family 25 Model 1 originale e dalle tre diagnosi precedenti.

WPR espone solo Timer; nessun PMC per retired instructions/cicli hardware.
QueryThreadCycleTime funziona, ma è contabilità Windows dei cicli del thread:
non sostituisce retired instructions, IPC o misura indipendente della frequenza.
CPU Wait Time Per Dispatch è UNAVAILABLE nella seconda sonda. Gli altri
contatori Hyper-V misurati appartengono all'ambito visibile del guest/nested
hypervisor: non dimostrano l'utilizzo o lo steal dell'host fisico di Azure.
Le due ETL power contengono solo due eventi di sistema, zero eventi del provider
Microsoft-Windows-Kernel-Processor-Power: registrazione/recording riusciti non
sono evidenza di una frequenza dinamica ETW disponibile.

## Esecuzione predefinita

Il wrapper scripts/observe_custodia_guest_frequency.ps1 è preparato e validato
solo come sintassi Windows dal run 38425341909. Nessun modello è stato caricato
in questa ripresa. Nessun workflow di qualifica originale è stato rieseguito.

Su una futura singola osservazione autorizzata, usare il medesimo bootstrap,
input locked, reader ETW e harness del branch diagnostico; non selezionare un
host in base al risultato. Il wrapper rilegge Actual Frequency sul guest reale
e rifiuta l'osservazione del modello se il canale è indisponibile/invalido. Con
reader ETW compilato e input locked già disponibili, il comando preparato è:

```powershell
./scripts/observe_custodia_guest_frequency.ps1 -Artifacts "$env:RUNNER_TEMP/diagnostic-inputs" -Output .agent/custodia-frequency-diagnosis
```

Mantiene le tre finestre en01–en04 fisse del precedente harness, source Core
cd7dc64f3ffb2a17689018b3350f0e1c073abdd4, affinity/priorità invariati. Campiona
insieme Actual Frequency, Processor Performance e Processor Time per core ogni
secondo; conserva QPC/UTC, status e timestamp PDH. Conservare anche JSON/PID/
request delle fasi, ETL raw e export numerico del reader precedente. NON usare
il workflow ai-runtime-candidate.yml per eseguire questa diagnosi.

## Decisione discriminante e rifiuti

Prima dell'analisi verificare QPC comune e conversione Python/.NET, usare gli
anchor QPC/UTC per collocare il timestamp di ciascun campione PDH; il QPC dopo
la raccolta non è il momento della misura. Con campioni a 1 s non attribuire
eventi di pochi ms a una frequenza puntuale. Richiedere almeno due campioni
validi che intersechino il decode rallentato, nessun gap/inversione di clock,
nessun evento ETW perso e copertura completa del decode. Un errore o fine
prematura del sampler rende la prova INCOMPLETE; la sua eccezione di stop
richiesta è distinta da una perdita durante l'osservazione.

Classificare le fasi del first-wall separatamente: admission/hash/load,
prefill nativo, ready/running ETW e IPC/dequeue. Confrontare frequenza riportata
e lavoro CPU nelle finestre fisse dello stesso nuovo host, senza sommare ready
aggregato dei thread alla latenza wall. Un rallentamento nativo con calo di
Actual Frequency e intervalli scheduler coperti è evidenza coerente con
prestazioni CPU inferiori nel NUOVO campione, non dimostrazione automatica di
causa fisica o difetto Core. Un ritardo ready/IPC con frequenza stabile richiede
la relativa evidenza di fase. Queste ipotesi possono risultare entrambe o
nessuna supportate; non forzare una classificazione.

Se nessun first-wall supera 5 s, il picco NON è riprodotto e l'analisi non
dimostra la causa originale. Fermarsi dopo la singola raccolta predefinita;
nessun retry invariato per scegliere un verde. Anche con rallentamento nuovo,
nessuna attribuzione retroattiva al campione originale. Una correzione Core
richiede un difetto dimostrato e PR/owner runtime separati. #348 resta bloccata
finché tutti i gate reali non sono soddisfatti; soltanto allora preflight fresco,
merge normale expected-head, parent/tree e post-merge.

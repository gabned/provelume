# Mirror SSH

Il trasporto opzionale invia generazioni complete in una sola direzione e
conserva quelle precedenti. La ricevuta richiede il puntatore alla generazione
attiva verificata: il solo successo di rsync non basta. Il mirror è una copia
derivata leggibile; non è archivio canonico né prova di backup.

Il primo profilo remoto usa una cartella Linux locale privata, con accessi
senza seguire alias e attivazione renameat2 qualificata. Servono rsync3.5.2,
protocollo33 e il profilo SSH esatto. Componenti mancanti o non supportati
impediscono la connessione prima dell’accesso alle credenziali. Windows usa
separatamente l’input MSYS2 fissato, con tutte le DLL: i metadati nel repository
non sono un eseguibile distribuito né un PASS Windows. Il
[contratto S22](../architecture/concordia-rsync-s22.md) distingue le prove.

1. Abilita esplicitamente mirror e permesso rsync. Crea un’identità dedicata con
   `mirror-rsync-create-identity INSTANCE nome.json --confirm`; il file esterno
   contiene solo `{"name":"Mirror SSH"}`. Esporta solo la chiave pubblica. Il
   segreto Ed25519 resta nell’archivio sicuro del sistema, senza file di chiave,
   argomenti o variabili d’ambiente.
2. Ottieni dal responsabile dell’host la chiave pubblica Ed25519 completa e
   verificane l’impronta. La chiave osservata durante una connessione non
   autorizza da sola il cambio del pin.
3. Sull’account remoto specificamente autorizzato installa l’helper revisionato.
   `provelume-rsync-helper enroll config.json --confirm` prepara un nuovo
   controllo privato e verifica una destinazione ancora assente, componenti ed
   esclusioni note. Il file dichiara `config_directory`, `root`, `source`
   (`instance_id`, `device_sha256`), `namespace` di32 caratteri esadecimali,
   `client_public_key`, `rsync_binary`, `excluded_roots`. L’output pubblico dà
   hash di configurazione, riga di chiave con comando forzato e sottosistema.
   L’installazione di queste autorizzazioni riguarda quell’account; il client
   non la esegue. Mantieni separati altri accessi e pubblicazione web.
4. Configura destinazione, ambito e include espliciti con profilo `rsync-ssh`.
   Il target ha campi scalari: `transport="rsync-ssh"`, `host`, `port` intera,
   `username`, `host_key` (blob SSH Ed25519 completo in base64), `namespace`,
   `configuration_sha256`, `bandwidth_kib`, `window_start_minute_utc`,
   `window_end_minute_utc`. La finestra è `[inizio,fine)` nei minuti0…1440 UTC;
   `[0,1440)` copre il giorno. Nessuna suddivisione notturna o aumento implicito.
5. `mirror-rsync-initialize` richiede hash esatto della destinazione e conferma.
   Prepara con `mirror-rsync-prepare`, controlla inventario e segnalazioni, poi
   pubblica con entrambi gli hash del piano. CLI e controlli CSRF nelle due
   interfacce usano lo stesso backend. Il profilo iniziale è privato: i permessi
   del filesystem non attestano un eventuale server web separato.

L’agent temporaneo firma una sola autenticazione legata a host, sessione e
utente. L’helper con comando forzato ammette un protocollo chiuso. La generazione
locale immutabile viene riletta; il remoto ricontrolla file e hash prima
dell’attivazione separata. Le generazioni precedenti restano.

Dopo un’interruzione, `mirror-rsync-reconcile PIANO --confirm` controlla senza
inviare. `mirror-rsync-resume PIANO --expected-rsync-plan-sha256 HASH --confirm`
richiede una richiesta esplicita, piano non scaduto, stessi permessi e chiave,
finestra UTC e banda. È possibile solo se un record durevole dimostra che il
ricevente è terminato e l’attivazione non è iniziata. Una generazione già
verificata passa alla prima attivazione senza nuovo invio. Un’attivazione
incerta resta UNKNOWN finché una prova in lettura della specifica operazione
non la chiarisce. Ripristinare Root non cancella il tentativo esterno registrato.

Lo scheduler attende fuori finestra; un errore effettivo richiede intervento
manuale e non provoca riprese automatiche. Con mirror/rsync disabilitati non ci
sono processi, accessi alle credenziali o contatti remoti. Lo stato passivo non
visita la destinazione. Scollegare revoca chiave e consenso locali; rimuovere la
chiave autorizzata sul server è un’operazione separata. Non ci sono adozione,
sincronizzazione inversa, pulizia o cancellazione della destinazione.

Test sintetici, esecuzione nativa, installer, browser e osservazioni umane
restano distinti. Tutti i manuali sono DEFERRED_BY_MAINTAINER / NOT_RUN fino alla
release ufficiale completata sul PC Windows11Pro25H2 del maintainer, senza
installazioni intermedie.

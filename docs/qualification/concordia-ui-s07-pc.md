# S07 — verifica personale sul PC Windows

Stato: **NOT_RUN**. La matrice originale T01–T48 e AC01–AC15 resta in
[#379](https://github.com/gabned/provelume/issues/379#issuecomment-6241608718).
Usare soltanto il candidato esatto e i digest indicati nel ledger di
[#438](https://github.com/gabned/provelume/pull/438), dopo la sua qualifica CI.
Il candidato mantiene **0.14.0/development**: non è la release finale 0.15.

La verifica è di Gabriele, sul suo PC Windows 11 Pro 25H2 e con il suo account
abituale. Non servono VM, altri account o tester. Le prove che richiedono un
profilo diverso restano NOT_RUN; non ereditano risultati dal runner Windows CI.

## Preparazione e stato iniziale

1. Annotare versione/build Windows e browser, commit del candidato e digest di
   installer e kit effettivamente usati. Il ledger deve riferirsi a questi byte.
2. Nella finestra desktop annotare lo spazio attuale, lingua, tema, interfaccia,
   avvio all’accesso e sorgenti già attive. Aprire il setup esistente e navigare
   senza azioni operative: identità, preferenze, documenti e consensi devono restare.
3. Per le azioni con effetti usare uno spazio sintetico nuovo, creato dalla
   finestra desktop in una cartella vuota, e una Inbox separata. È un normale
   spazio locale sullo stesso PC/account. Inserire nella Inbox un piccolo file
   sentinella sintetico prima di prepararla: non deve essere acquisito dalla prova.

Non usare documenti personali come fixture. Non cancellare l’archivio o ripulire
le cartelle per rendere verde un esito. Uscire o scartare la bozza conserva quanto
è stato realmente preparato, installato, acquisito o applicato.

## Percorso senza OCR

- Aprire **Configura Provelume** dalla finestra desktop o da Acquisizione/Sorgenti.
  Verificare spazio e lingua; il menu lingua della pagina è un’anteprima.
- In **Cartelle e Inbox** scegliere la cartella sintetica. Prima di **Prepara e
  verifica** non deve partire alcuna acquisizione. Dopo, verificare percorso,
  comportamento proposto e assenza di modifiche alla sentinella.
- Scegliere **Non ora** per OCR, e acquisizione **su comando**. Il limite di
  ricerca delle scansioni deve restare visibile; nessun badge OCR pronto.
- Avviare la prova: solo il PDF nativo mostrato deve entrare nel flusso. Attendere
  i risultati effettivi, aggiornando lo stato. Aprire Documento e Originale e usare
  la ricerca nel contenuto suggerita. **Verifica apertura** deve rileggere le
  risposte reali, senza dedurre il successo da un click.
- Provare sia conserva-file sia transito con azioni di prova distinte. In transito
  esce soltanto la copia sintetica completata; l’Originale resta apribile. Con
  conserva-file l’input resta intenzionalmente. La sentinella resta intatta.
- Applicare dal riepilogo. Riaprire lingua, Source e setup: devono concordare con
  le scelte salvate. La modalità su comando non deve apparire come attività
  automatica. Gli input già presenti non devono essere acquisiti dall’Apply.

## Percorso OCR locale

- Scegliere OCR per la sola Source sintetica e IT/EN. Controllare separatamente
  disponibilità effettiva dei componenti e scelta desiderata.
- Dal kit locale esatto, leggere l’anteprima con ricevuta release corrispondente
  oppure SHA-256 pubblicato verificato indipendentemente. Per un kit candidato,
  usare il fingerprint del medesimo candidato; non riutilizzare un kit di un altro
  commit. Anteprima e annullamento non installano; **Prepara OCR locale** è
  separato da consenso Source, arretrato e prova. Nessun download o configurazione
  di Python, librerie o PATH è necessario.
- Avviare una nuova prova esplicita: PDF nativo e scansione sintetica devono
  essere acquisiti automaticamente nel perimetro mostrato. Il nativo salta OCR;
  la scansione riceve testo OCR reale. Cercare i token italiani/inglesi nel
  contenuto e aprire entrambi gli Originali. Nessun OCR manuale qualifica la prova.
- Applicare e leggere gli esiti, poi aggiungere un nuovo PDF sintetico alla Inbox
  attraverso la normale acquisizione. Il comportamento futuro deve usare gli
  stessi servizi e consensi, senza un secondo osservatore.

## Ripresa, uso quotidiano e accessibilità

- Chiudere soltanto il browser durante l’attesa, poi riaprire: l’operazione non
  deve duplicarsi né essere dichiarata annullata. Provare doppio click, seconda
  scheda, Indietro, salva/riprendi e scarta. I Documenti acquisiti restano.
- Cambiare una preferenza da un’altra scheda prima di Apply: il conflitto deve
  richiedere revisione e conservare il valore nuovo. Se esiste un Apply parziale,
  leggere l’elenco degli effetti; **Metti in pausa e rivedi** conserva dati e
  impostazioni applicate. Nessun successo globale su un esito incompleto.
- Seguire Acquisizione → Sorgenti → Documento e ritorno al setup. Distinguere
  file presenti, lavoro da completare, stato OCR/indice e runtime attivo/fermo.
  Libreria, Originale e cartella d’ingresso devono avere ruoli chiari.
- Provare Current e Cura, temi chiaro/scuro/Sistema e sette lingue più Sistema.
  Usare solo tastiera per selettori, errori, indice, pulsanti e uscita. Controllare
  focus visibile, campi e testi completi alle larghezze 320/375/736/1024px.
- Usare **zoom reale del browser al 200%**, controllandolo nel menu del browser.
  L’emulazione di viewport non sostituisce questa prova. Con Narratore di Windows,
  verificare annunci di tappa, controlli, errori e avanzamento. Questi restano
  risultati umani distinti da screenshot e misure DOM.
- Il difetto noto di `/sources` in spagnolo a 320px resta aperto: annotare il
  risultato, senza considerarlo risolto dalla diversa pagina di setup.

Non occorre provocare crash distruttivi o corrompere dati personali sul PC di
produzione. Le varianti non eseguite della matrice restano NOT_RUN; i fault
sintetici automatici hanno un’evidenza separata. Upgrade/versioni/edizioni non
provati restano nel proprio gate del piano, senza un PASS implicito.

## Esiti da registrare

Riportare commit/asset, ambiente, caso Txx/ACxx, azione, risultato osservato e
PASS/FAIL/NOT_RUN. Per un FAIL indicare il punto esatto e gli effetti già presenti;
non basta un riepilogo “tutto funziona”. Un esito manuale vale soltanto per il
profilo realmente usato. S07 e l’owner successivo non si accettano per deduzione.

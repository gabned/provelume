from __future__ import annotations

TEXT = {
    "google_legacy_connection": (
        "This manually configured connection has no verified account binding for the guided "
        "journey. Keep using its advanced controls, or create a separate guided connection.",
        "Questa connessione configurata manualmente non ha un'identità account verificabile "
        "per il percorso guidato. Usa i controlli avanzati o crea una connessione "
        "guidata separata.",
    ),
    "network": ("Instance network access", "Accesso alla rete dell'istanza"),
    "network_consent": (
        "I confirm this changes external network access for the entire Instance, including "
        "other explicitly enabled connectors. It does not change LAN or firewall settings.",
        "Confermo la modifica dell'accesso alla rete esterna per l'intera istanza, inclusi gli "
        "altri connettori esplicitamente abilitati. Non modifica LAN o firewall.",
    ),
    "enable_network": ("Allow external access", "Consenti accesso esterno"),
    "disable_network": ("Go offline", "Passa offline"),
    "google_network_enabled": (
        "External access is allowed. Each connector, capability and Source still needs "
        "its own explicit authorization and enablement.",
        "Accesso esterno consentito. Ogni connettore, capability e Source richiede comunque "
        "la propria autorizzazione e abilitazione esplicita.",
    ),
    "succeeded": ("Completed", "Completato"),
    "title": ("Connect Google", "Connetti Google"),
    "lead": (
        "Connect Gmail and Drive separately, with read-only access. Your existing Originals "
        "stay available offline and after disconnecting.",
        "Connetti Gmail e Drive separatamente, in sola lettura. Gli Originals già acquisiti "
        "restano disponibili offline e dopo la disconnessione.",
    ),
    "name": ("Connection name", "Nome della connessione"),
    "gmail": ("Gmail", "Gmail"),
    "drive": ("Google Drive", "Google Drive"),
    "consent": (
        "I agree to connect only the selected service with read-only access.",
        "Acconsento a connettere solo il servizio selezionato in sola lettura.",
    ),
    "service": ("Service", "Servizio"),
    "connect": ("Connect", "Connetti"),
    "reconnect": ("Reconnect", "Riconnetti"),
    "test": ("Test connection", "Verifica connessione"),
    "disconnect": ("Disconnect this service", "Disconnetti questo servizio"),
    "cancel_consent": ("Cancel pending consent", "Annulla consenso in corso"),
    "connected": ("Connected", "Connesso"),
    "expired": ("Expired — reconnect", "Scaduto — riconnetti"),
    "revoked": ("Revoked / disconnected", "Revocato / disconnesso"),
    "disconnected": ("Not connected", "Non connesso"),
    "setup": ("Set up the Google desktop client", "Configura il client desktop Google"),
    "setup_help": (
        "One-time setup: paste the installed-app client JSON downloaded from your authorized "
        "Google project. It is kept in your system credential store, outside the Instance. "
        "Enable Gmail and Drive APIs and authorize your test account in that project.",
        "Configurazione iniziale: incolla il JSON del client per app installata scaricato dal "
        "tuo progetto Google autorizzato. È conservato nell'archivio credenziali di sistema, "
        "fuori dall'istanza. Abilita le API Gmail e Drive e autorizza il tuo account di test.",
    ),
    "client_json": ("Desktop client JSON", "JSON del client desktop"),
    "save_client": ("Save securely", "Salva in modo sicuro"),
    "sources": ("Google Sources", "Source Google"),
    "bounds": (
        "Start reads your mailbox or the files directly in My Drive: at most 2 pages, 50 items "
        "and 64 MiB per run (32 MiB per item). Continue resumes the saved checkpoint. "
        "Folders inside My Drive need their own selection in the advanced controls.",
        "Avvia legge la casella Gmail o i file direttamente in Il mio Drive: al massimo 2 pagine, "
        "50 elementi e 64 MiB per esecuzione (32 MiB per elemento). Continua riprende dal punto "
        "salvato. Le sottocartelle di Drive richiedono una selezione nei controlli avanzati.",
    ),
    "start": ("Start bounded intake", "Avvia acquisizione limitata"),
    "continue": ("Continue / retry", "Continua / riprova"),
    "jobs": ("Intake activity", "Attività di acquisizione"),
    "cancel": ("Cancel intake", "Annulla acquisizione"),
    "refresh": ("Refresh status", "Aggiorna stato"),
    "advanced": ("Advanced Google controls", "Controlli Google avanzati"),
    "local_only": (
        "Connect from the browser on the computer hosting this Instance.",
        "Connettiti dal browser sul computer che ospita questa istanza.",
    ),
    "revoke": ("Revoke Google project access", "Revoca accesso del progetto Google"),
    "revoke_help": (
        "Google revokes all grants for this OAuth project, including Gmail, Drive and other "
        "clients of that project. Local disconnect affects only the selected service here.",
        "Google revoca tutti i consensi del progetto OAuth, inclusi Gmail, Drive e gli altri "
        "client del progetto. La disconnessione locale riguarda solo il servizio selezionato qui.",
    ),
    "revoke_consent": (
        "I authorize revocation for the entire Google project.",
        "Autorizzo la revoca per l'intero progetto Google.",
    ),
    "google_network_disabled": (
        "Offline: enable external network access in Instance settings and enable this connector "
        "before connecting. No credential or network access was attempted.",
        "Offline: abilita l'accesso alla rete esterna nelle impostazioni dell'istanza e abilita "
        "il connettore prima di connetterti. Nessun accesso a credenziali o rete è stato tentato.",
    ),
    "google_client_required": (
        "Complete the desktop client setup below, then connect again.",
        "Completa la configurazione del client desktop, poi riconnettiti.",
    ),
    "google_client_invalid": (
        "Use the downloaded installed-app desktop client JSON.",
        "Usa il JSON scaricato del client desktop per app installata.",
    ),
    "google_secure_store_unavailable": (
        "Unlock your system credential store and retry. Windows requires the same signed-in "
        "user; Linux requires an unlocked Secret Service; macOS requires Keychain access.",
        "Sblocca l'archivio credenziali di sistema e riprova. Windows richiede lo stesso utente "
        "connesso; Linux richiede Secret Service sbloccato; macOS richiede accesso al Portachiavi.",
    ),
    "google_consent_required": (
        "Confirm the explicit consent before continuing.",
        "Conferma il consenso esplicito prima di continuare.",
    ),
    "google_scope_mismatch": (
        "The returned grant has different permissions. Reconnect with "
        "only this service's read-only scope.",
        "Il consenso restituito ha permessi diversi. Riconnetti con il "
        "solo ambito di lettura di questo servizio.",
    ),
    "google_account_mismatch": (
        "Choose the account originally connected to this connection.",
        "Scegli l'account originariamente associato a questa connessione.",
    ),
    "google_connection_failed": (
        "Google could not be reached or rejected the request. Check "
        "connectivity and the authorized desktop client, then retry.",
        "Google non è raggiungibile o ha rifiutato la richiesta. Controlla "
        "la connessione e il client desktop autorizzato, poi riprova.",
    ),
    "google_reconnect_required": (
        "Authorization expired or was revoked. Reconnect this service.",
        "Autorizzazione scaduta o revocata. Riconnetti questo servizio.",
    ),
    "google_callback_invalid": (
        "Consent expired, was cancelled or did not match. Start again.",
        "Consenso scaduto, annullato o non corrispondente. Ricomincia.",
    ),
    "google_connection_busy": (
        "Cancel an earlier pending consent before starting another.",
        "Annulla un consenso già in corso prima di iniziarne un altro.",
    ),
    "google_client_saved": (
        "Desktop client saved securely.",
        "Client desktop salvato in sicurezza.",
    ),
    "google_connected": (
        "Connection test passed. Start intake when ready.",
        "Verifica della connessione riuscita. Avvia l'acquisizione quando vuoi.",
    ),
    "google_disconnected": (
        "Service disconnected locally. Acquired content is retained.",
        "Servizio disconnesso localmente. I contenuti acquisiti sono conservati.",
    ),
    "google_project_revoked": (
        "Project access revoked. Affected local services are disconnected.",
        "Accesso del progetto revocato. Servizi locali coinvolti disconnessi.",
    ),
    "google_consent_cancelled": ("Pending consent cancelled.", "Consenso in corso annullato."),
    "google_queued": (
        "Bounded intake queued. Refresh to see progress; cancel at any time.",
        "Acquisizione limitata in coda. Aggiorna per vedere l'avanzamento; puoi annullare.",
    ),
    "google_cancelled": (
        "Cancellation requested. Already acquired Originals are retained.",
        "Annullamento richiesto. Gli Originals già acquisiti sono conservati.",
    ),
    "queued": ("Queued", "In coda"),
    "running": ("Running", "In corso"),
    "completed": ("Completed", "Completato"),
    "completed_with_errors": ("Completed with errors", "Completato con errori"),
    "continuation_available": ("More items available — continue", "Altri elementi — continua"),
    "failed": ("Failed — check connection and retry", "Non riuscito — verifica e riprova"),
    "cancelled": ("Cancelled", "Annullato"),
    "retry_wait": ("Waiting for retry", "In attesa di retry"),
    "processed": ("Acquired", "Acquisiti"),
    "skipped": ("Already present", "Già presenti"),
    "errors": ("Errors", "Errori"),
}


def connection_translator(language):
    position = 1 if language == "it" else 0

    def translate(key):
        return TEXT.get(key, TEXT["google_connection_failed"])[position]

    return translate

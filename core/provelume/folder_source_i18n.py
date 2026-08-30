from __future__ import annotations

FOLDER_SOURCE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.sources": "Sources",
        "sources.eyebrow": "Explicit filesystem scope",
        "sources.title": "Folder Sources",
        "sources.lead": (
            "Register local, removable or mounted-network folders, wait for a stable "
            "snapshot, then refresh through the durable scheduler journal."
        ),
        "sources.register": "Register a folder Source",
        "sources.name": "Name",
        "sources.path": "Filesystem path",
        "sources.class": "Source class",
        "sources.state": "Initial state",
        "sources.quiescence": "Quiescence seconds",
        "sources.stable": "Stable observations",
        "sources.watch": "Watch interval seconds (blank for manual)",
        "sources.timezone": "Timezone",
        "sources.submit": "Register Source",
        "sources.inventory": "Managed Sources",
        "sources.empty": "No managed folder Source is configured.",
        "sources.files": "Observed files",
        "sources.bytes": "Observed bytes",
        "sources.policy": "Scheduler policy",
        "sources.observe": "Observe",
        "sources.refresh": "Queue refresh",
        "sources.enable": "Enable",
        "sources.pause": "Pause",
        "sources.saved": "Folder Source change accepted.",
        "sources.error": "The folder Source change was rejected.",
        "sources.remote_readonly": (
            "Folder paths and controls are available only in the local browser."
        ),
        "sources.boundary_title": "Safety boundary",
        "sources.boundary": (
            "A missing mount preserves all canonical records. Observation stores only counts, "
            "timestamps and fingerprints; it never stores document content or deletes files."
        ),
    },
    "it": {
        "nav.sources": "Sorgenti",
        "sources.eyebrow": "Ambito filesystem esplicito",
        "sources.title": "Source da cartelle",
        "sources.lead": (
            "Registra cartelle locali, rimovibili o di rete montate, attendi uno snapshot "
            "stabile, quindi aggiorna tramite il journal durevole dello scheduler."
        ),
        "sources.register": "Registra una Source da cartella",
        "sources.name": "Nome",
        "sources.path": "Percorso filesystem",
        "sources.class": "Classe Source",
        "sources.state": "Stato iniziale",
        "sources.quiescence": "Secondi di quiescenza",
        "sources.stable": "Osservazioni stabili",
        "sources.watch": "Intervallo di watch in secondi (vuoto per manuale)",
        "sources.timezone": "Fuso orario",
        "sources.submit": "Registra Source",
        "sources.inventory": "Source gestite",
        "sources.empty": "Non è configurata alcuna Source da cartella gestita.",
        "sources.files": "File osservati",
        "sources.bytes": "Byte osservati",
        "sources.policy": "Policy scheduler",
        "sources.observe": "Osserva",
        "sources.refresh": "Accoda refresh",
        "sources.enable": "Abilita",
        "sources.pause": "Metti in pausa",
        "sources.saved": "Modifica della Source accettata.",
        "sources.error": "La modifica della Source è stata rifiutata.",
        "sources.remote_readonly": "Percorsi e controlli sono disponibili solo nel browser locale.",
        "sources.boundary_title": "Confine di sicurezza",
        "sources.boundary": (
            "Un mount mancante preserva tutti i record canonici. L'osservazione conserva solo "
            "conteggi, timestamp e fingerprint; non salva contenuti e non cancella file."
        ),
    },
}

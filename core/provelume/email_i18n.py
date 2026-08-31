from __future__ import annotations

EMAIL_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.email": "Local email",
        "email.eyebrow": "Explicit offline intake",
        "email.title": "Local email intake",
        "email.lead": (
            "Import exact EML or qualified Maildir bytes without provider access. "
            "Headers, bodies and observed threads remain removable derived state."
        ),
        "email.saved": "Email control applied",
        "email.error": "Email control failed",
        "email.local_only": "Mutating controls are available only from the loopback browser.",
        "email.capability": "Effective capability",
        "email.profile": "Profile",
        "email.available": "Available",
        "email.reason": "Reason",
        "email.limits": "Effective limits",
        "email.runtime": "No network, runtime download or remote fallback",
        "email.attachment_ocr": "Attachment OCR boundary",
        "email.ocr_separate": (
            "Separate from email intake; OCR always requires its own explicit job"
        ),
        "email.create": "Create a disabled Source",
        "email.name": "Name",
        "email.path": "Explicit local path",
        "email.create_action": "Create Source",
        "email.sources": "Configured Sources",
        "email.no_sources": "No local email Source is configured.",
        "email.enable": "Enable",
        "email.pause": "Pause",
        "email.disable": "Disable",
        "email.remove_source": "Remove Source",
        "email.schedule": "Schedule",
        "email.interval": "Interval seconds",
        "email.save_schedule": "Save schedule",
        "email.queue": "Run now",
        "email.jobs": "Durable intake jobs",
        "email.no_jobs": "No email intake job has been journaled.",
        "email.run": "Execute",
        "email.cancel": "Cancel",
        "email.messages": "Messages",
        "email.no_messages": "No email message has been acquired.",
        "email.inspect": "Inspect",
        "email.threads": "Observed threads",
        "email.no_threads": "No observed thread is available.",
        "email.attachments": "Attachments",
        "email.no_attachments": "No accepted attachment is available.",
        "email.remove_derived": "Remove derived representation",
        "email.rebuild_derived": "Rebuild from Original",
        "email.back": "Back to local email",
        "email.passive": (
            "HTML, scripts, CSS, remote images, links and attachments are never executed "
            "or fetched. OCR eligibility never starts OCR."
        ),
    },
    "it": {
        "nav.email": "Email locale",
        "email.eyebrow": "Intake offline esplicito",
        "email.title": "Intake email locale",
        "email.lead": (
            "Importa byte EML o Maildir qualificati senza accesso a provider. Header, body "
            "e thread osservati restano stato derivato rimovibile."
        ),
        "email.saved": "Controllo email applicato",
        "email.error": "Controllo email non riuscito",
        "email.local_only": "I controlli di modifica sono disponibili solo nel browser loopback.",
        "email.capability": "Capability effettiva",
        "email.profile": "Profilo",
        "email.available": "Disponibile",
        "email.reason": "Motivo",
        "email.limits": "Limiti effettivi",
        "email.runtime": "Nessuna rete, download runtime o fallback remoto",
        "email.attachment_ocr": "Confine OCR degli allegati",
        "email.ocr_separate": (
            "Separato dall'intake email; l'OCR richiede sempre un proprio job esplicito"
        ),
        "email.create": "Crea una Source disabilitata",
        "email.name": "Nome",
        "email.path": "Percorso locale esplicito",
        "email.create_action": "Crea Source",
        "email.sources": "Source configurate",
        "email.no_sources": "Nessuna Source email locale è configurata.",
        "email.enable": "Abilita",
        "email.pause": "Metti in pausa",
        "email.disable": "Disabilita",
        "email.remove_source": "Rimuovi Source",
        "email.schedule": "Pianificazione",
        "email.interval": "Intervallo in secondi",
        "email.save_schedule": "Salva pianificazione",
        "email.queue": "Esegui ora",
        "email.jobs": "Job di intake durevoli",
        "email.no_jobs": "Nessun job di intake email è stato registrato.",
        "email.run": "Esegui",
        "email.cancel": "Annulla",
        "email.messages": "Messaggi",
        "email.no_messages": "Nessun messaggio email è stato acquisito.",
        "email.inspect": "Ispeziona",
        "email.threads": "Thread osservati",
        "email.no_threads": "Nessun thread osservato è disponibile.",
        "email.attachments": "Allegati",
        "email.no_attachments": "Nessun allegato accettato è disponibile.",
        "email.remove_derived": "Rimuovi rappresentazione derivata",
        "email.rebuild_derived": "Ricostruisci dall'Original",
        "email.back": "Torna a email locale",
        "email.passive": (
            "HTML, script, CSS, immagini remote, link e allegati non vengono mai eseguiti "
            "o caricati. L'idoneità OCR non avvia mai OCR."
        ),
    },
}

__all__ = ["EMAIL_TRANSLATIONS"]

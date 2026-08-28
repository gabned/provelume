from __future__ import annotations

FOLDER_SETTINGS_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.settings": "Settings",
        "settings.eyebrow": "Instance-local configuration",
        "settings.title": "Folder settings",
        "settings.lead": (
            "Choose the Inbox name and the local folders used for incoming files and "
            "managed copies. Relative paths stay inside the Instance; absolute paths may "
            "point elsewhere on this computer."
        ),
        "settings.local_only": (
            "Changes are accepted only from the local browser or CLI and are recorded "
            "without physical paths in the Operations log."
        ),
        "settings.remote_readonly": (
            "This view is read-only because the request is not local. External physical "
            "paths are redacted."
        ),
        "settings.saved": "Folder settings were validated and saved.",
        "settings.error": "Settings were not changed",
        "settings.inbox_name": "Inbox display name",
        "settings.drop_path": "Drop folder",
        "settings.managed_path": "Managed-copy folder",
        "settings.drop_help": (
            "Files placed here can be processed with move-after-verified-commit semantics."
        ),
        "settings.managed_help": (
            "Provelume keeps hash-verified working copies here before canonical acquisition."
        ),
        "settings.save": "Save folder settings",
        "settings.scope": "Location",
        "settings.internal": "Inside the Instance",
        "settings.external": "External filesystem folder",
        "settings.available": "Available",
        "settings.unavailable": "Unavailable",
        "settings.writable": "Writable",
        "settings.not_writable": "Not writable",
        "settings.relocation_allowed": "Managed folder can still be changed",
        "settings.relocation_blocked": (
            "Managed folder relocation is locked because Inbox acquisitions already exist. "
            "The name and Drop folder may still change."
        ),
        "settings.canonical_inside": (
            "Canonical Originals, knowledge, indexes, operation logs and reports remain "
            "inside the Instance."
        ),
        "settings.cli": "The same settings are available through",
        "inbox.drop_help": "Place supported files in the configured Drop folder",
    },
    "it": {
        "nav.settings": "Impostazioni",
        "settings.eyebrow": "Configurazione locale dell'istanza",
        "settings.title": "Impostazioni cartelle",
        "settings.lead": (
            "Scegli il nome dell'Inbox e le cartelle locali usate per i file in ingresso "
            "e le copie gestite. I percorsi relativi restano nell'istanza; quelli assoluti "
            "possono puntare altrove sul computer."
        ),
        "settings.local_only": (
            "Le modifiche sono accettate soltanto dal browser locale o dalla CLI e vengono "
            "registrate nel log Operazioni senza salvare i percorsi fisici."
        ),
        "settings.remote_readonly": (
            "Questa vista è in sola lettura perché la richiesta non è locale. I percorsi "
            "fisici esterni sono oscurati."
        ),
        "settings.saved": "Le impostazioni delle cartelle sono state validate e salvate.",
        "settings.error": "Le impostazioni non sono state modificate",
        "settings.inbox_name": "Nome visualizzato dell'Inbox",
        "settings.drop_path": "Cartella Drop",
        "settings.managed_path": "Cartella delle copie gestite",
        "settings.drop_help": (
            "I file inseriti qui possono essere lavorati con spostamento solo dopo un "
            "commit verificato."
        ),
        "settings.managed_help": (
            "Provelume conserva qui copie di lavoro verificate tramite hash prima "
            "dell'acquisizione canonica."
        ),
        "settings.save": "Salva impostazioni cartelle",
        "settings.scope": "Posizione",
        "settings.internal": "Dentro l'istanza",
        "settings.external": "Cartella esterna del filesystem",
        "settings.available": "Disponibile",
        "settings.unavailable": "Non disponibile",
        "settings.writable": "Scrivibile",
        "settings.not_writable": "Non scrivibile",
        "settings.relocation_allowed": "La cartella gestita può ancora essere cambiata",
        "settings.relocation_blocked": (
            "Lo spostamento della cartella gestita è bloccato perché esistono già "
            "acquisizioni Inbox. Nome e cartella Drop possono ancora cambiare."
        ),
        "settings.canonical_inside": (
            "Original canonici, conoscenza, indici, log operazioni e report restano "
            "all'interno dell'istanza."
        ),
        "settings.cli": "Le stesse impostazioni sono disponibili tramite",
        "inbox.drop_help": "Inserisci i file supportati nella cartella Drop configurata",
    },
}

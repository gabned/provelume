from __future__ import annotations

SHELL_TRANSLATIONS = {
    "en": {
        "nav.group.knowledge": "Knowledge",
        "nav.group.status": "Operational status",
        "nav.group.configuration": "Configuration",
        "nav.group.maintenance": "Maintenance",
        "nav.group.support": "Diagnostics & support",
        "nav.shell": "Shell & endpoint",
        "shell.eyebrow": "Installed Windows shell",
        "shell.title": "Shell & local endpoint",
        "shell.lead": (
            "Inspect and explicitly change bounded shell preferences. The service always binds "
            "to loopback and never selects a random port."
        ),
        "shell.endpoint": "Local endpoint",
        "shell.active_endpoint": "Active service endpoint",
        "shell.configured_endpoint": "Configured restart endpoint",
        "shell.port": "Port",
        "shell.port_help": "Allowed range: 1024–65535. Default: 44851.",
        "shell.binding": "Binding",
        "shell.loopback": "Loopback only",
        "shell.source": "Configuration source",
        "shell.restart": "Restart required",
        "shell.tray": "Use the system tray by default",
        "shell.login": "Start at Windows login (separate opt-in)",
        "shell.login_unavailable": "Available only in the installed Windows shell.",
        "shell.theme": "Theme",
        "shell.theme.system": "System",
        "shell.theme.light": "Light",
        "shell.theme.dark": "Dark",
        "shell.language": "Interface language",
        "shell.save": "Validate and save",
        "shell.reset": "Restore port 44851",
        "shell.saved": "Shell preferences were saved atomically.",
        "shell.reset_done": "The default port 44851 was restored.",
        "shell.error": "The change was not applied.",
        "shell.error.shell_settings_error": "One or more shell settings are invalid.",
        "shell.error.port_unavailable": "The selected loopback port is occupied.",
        "shell.error.stale_configuration": (
            "The settings changed after this page loaded. Reload and try again."
        ),
        "shell.error.configuration_busy": (
            "Another shell settings operation is active. Wait and try again."
        ),
        "shell.error.preferences_invalid": "The portable preference document is invalid.",
        "shell.local_only": (
            "Changes require local service authorization, CSRF protection, a one-time request "
            "reference and the current configuration revision."
        ),
        "shell.remote_readonly": "This surface is read-only outside the local Browser shell.",
        "shell.warning": "Configuration warning",
        "shell.service": "Service status",
        "shell.running": "Running locally",
        "shell.schema": "Configuration schema",
        "shell.revision": "Revision",
        "shell.limits": "Safety limits",
        "shell.no_random": "No random fallback",
        "shell.no_firewall": "No firewall change",
        "shell.no_remote": "No remote binding",
        "shell.restart_plan": (
            "A port change is persisted first and requires an explicit service restart. If "
            "startup fails, the previous known endpoint can be restored without choosing a new one."
        ),
        "shell.unsigned": (
            "This development installer is unsigned. Windows may show Unknown publisher until an "
            "authorized Authenticode certificate, valid chain and timestamp are verified on the "
            "exact artifact."
        ),
    },
    "it": {
        "nav.group.knowledge": "Conoscenza",
        "nav.group.status": "Stato operativo",
        "nav.group.configuration": "Configurazione",
        "nav.group.maintenance": "Manutenzione",
        "nav.group.support": "Diagnostica e supporto",
        "nav.shell": "Shell ed endpoint",
        "shell.eyebrow": "Shell Windows installata",
        "shell.title": "Shell ed endpoint locale",
        "shell.lead": (
            "Ispeziona e modifica esplicitamente preferenze shell limitate. Il servizio resta "
            "sempre sul loopback e non sceglie mai una porta casuale."
        ),
        "shell.endpoint": "Endpoint locale",
        "shell.active_endpoint": "Endpoint attivo del servizio",
        "shell.configured_endpoint": "Endpoint configurato per il riavvio",
        "shell.port": "Porta",
        "shell.port_help": "Intervallo ammesso: 1024–65535. Predefinita: 44851.",
        "shell.binding": "Binding",
        "shell.loopback": "Solo loopback",
        "shell.source": "Origine della configurazione",
        "shell.restart": "Riavvio necessario",
        "shell.tray": "Usa l'area di notifica per impostazione predefinita",
        "shell.login": "Avvia all'accesso a Windows (scelta separata)",
        "shell.login_unavailable": "Disponibile soltanto nella shell Windows installata.",
        "shell.theme": "Tema",
        "shell.theme.system": "Sistema",
        "shell.theme.light": "Chiaro",
        "shell.theme.dark": "Scuro",
        "shell.language": "Lingua dell'interfaccia",
        "shell.save": "Valida e salva",
        "shell.reset": "Ripristina la porta 44851",
        "shell.saved": "Le preferenze shell sono state salvate atomicamente.",
        "shell.reset_done": "È stata ripristinata la porta predefinita 44851.",
        "shell.error": "La modifica non è stata applicata.",
        "shell.error.shell_settings_error": "Una o più impostazioni shell non sono valide.",
        "shell.error.port_unavailable": "La porta loopback scelta è occupata.",
        "shell.error.stale_configuration": (
            "Le impostazioni sono cambiate dopo il caricamento. Ricarica e riprova."
        ),
        "shell.error.configuration_busy": (
            "È attiva un'altra operazione sulle impostazioni shell. Attendi e riprova."
        ),
        "shell.error.preferences_invalid": "Il documento portatile delle preferenze non è valido.",
        "shell.local_only": (
            "Le modifiche richiedono autorizzazione del servizio locale, protezione CSRF, un "
            "riferimento monouso e la revisione corrente della configurazione."
        ),
        "shell.remote_readonly": (
            "Questa superficie è in sola lettura fuori dalla shell Browser locale."
        ),
        "shell.warning": "Avviso di configurazione",
        "shell.service": "Stato del servizio",
        "shell.running": "In esecuzione in locale",
        "shell.schema": "Schema di configurazione",
        "shell.revision": "Revisione",
        "shell.limits": "Limiti di sicurezza",
        "shell.no_random": "Nessun fallback casuale",
        "shell.no_firewall": "Nessuna modifica al firewall",
        "shell.no_remote": "Nessun binding remoto",
        "shell.restart_plan": (
            "La modifica della porta viene prima persistita e richiede un riavvio esplicito del "
            "servizio. Se l'avvio fallisce, si può ripristinare l'endpoint precedente noto senza "
            "sceglierne uno nuovo."
        ),
        "shell.unsigned": (
            "Questo installer di sviluppo non è firmato. Windows può mostrare Editore sconosciuto "
            "finché certificato Authenticode autorizzato, catena valida e timestamp non sono "
            "verificati sull'artefatto esatto."
        ),
    },
}

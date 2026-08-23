from __future__ import annotations

from collections.abc import Callable

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "security.title": "Security",
        "security.intro": (
            "Inspect local package integrity and declared network capability without "
            "sending Instance data anywhere."
        ),
        "security.installation.title": "Verify installation",
        "security.installation.detail": (
            "Check installed Core package bytes and keep integrity separate from official origin."
        ),
        "security.network.title": "Privacy & Network Activity",
        "security.network.detail": (
            "Review which components can communicate externally, what is enabled and "
            "which information is not yet observable."
        ),
        "network.title": "Privacy & Network Activity",
        "network.intro": (
            "This page reports declared capability and configuration. The check itself "
            "uses no network and does not expose source paths or secrets."
        ),
        "policy.local_only": "Local-only baseline",
        "policy.explicit_external_access": "External access explicitly configured",
        "policy.configuration_conflict": "Network configuration needs attention",
        "label.policy": "Effective policy",
        "label.external_allowed": "External access allowed",
        "label.components": "Components",
        "label.configured_external": "Configured external components",
        "label.effective_external": "Effectively enabled external components",
        "label.endpoints": "Declared endpoint origins",
        "label.issues": "Issues",
        "label.observed": "Observed activity",
        "yes": "Yes",
        "no": "No",
        "observed.not_instrumented": "Not instrumented",
        "components.title": "Declared components",
        "components.empty": "No components were declared.",
        "component.enabled": "Configured",
        "component.effective": "Effective",
        "component.network_capable": "Network capable",
        "component.implementation": "Implementation",
        "component.endpoints": "Endpoints",
        "component.categories": "Data categories",
        "component.none": "None declared",
        "capability.local": "No",
        "capability.external": "Yes",
        "capability.undeclared": "Undeclared",
        "issues.title": "Problems and unknowns",
        "issues.none": "No network-policy problem was detected.",
        "issue.capability_undeclared": "Capability not declared",
        "issue.configured_but_unavailable": "Configured but unavailable",
        "issue.endpoint_undeclared": "Endpoint not declared",
        "issue.invalid_endpoint": "Invalid or redacted endpoint",
        "issue.policy_conflict": "Policy conflict",
        "issue.invalid_declaration": "Invalid declaration",
        "issue.component_limit": "Safety limit reached",
        "back.security": "Security",
        "back.home": "Home",
    },
    "it": {
        "security.title": "Sicurezza",
        "security.intro": (
            "Controlla l'integrità locale del pacchetto e le capacità di rete dichiarate "
            "senza inviare altrove i dati della Instance."
        ),
        "security.installation.title": "Verifica installazione",
        "security.installation.detail": (
            "Controlla i file del Core installato separando integrità e origine ufficiale."
        ),
        "security.network.title": "Privacy e attività di rete",
        "security.network.detail": (
            "Controlla quali componenti possono comunicare all'esterno, cosa è abilitato "
            "e quali informazioni non sono ancora osservabili."
        ),
        "network.title": "Privacy e attività di rete",
        "network.intro": (
            "Questa pagina mostra capacità e configurazione dichiarate. Il controllo non "
            "usa la rete e non espone percorsi delle fonti né segreti."
        ),
        "policy.local_only": "Configurazione solo locale",
        "policy.explicit_external_access": "Accesso esterno configurato esplicitamente",
        "policy.configuration_conflict": "Configurazione di rete da controllare",
        "label.policy": "Policy effettiva",
        "label.external_allowed": "Accesso esterno consentito",
        "label.components": "Componenti",
        "label.configured_external": "Componenti esterni configurati",
        "label.effective_external": "Componenti esterni effettivamente attivi",
        "label.endpoints": "Origini endpoint dichiarate",
        "label.issues": "Problemi",
        "label.observed": "Attività osservata",
        "yes": "Sì",
        "no": "No",
        "observed.not_instrumented": "Non strumentata",
        "components.title": "Componenti dichiarati",
        "components.empty": "Non sono stati dichiarati componenti.",
        "component.enabled": "Configurato",
        "component.effective": "Effettivo",
        "component.network_capable": "Può usare la rete",
        "component.implementation": "Implementazione",
        "component.endpoints": "Endpoint",
        "component.categories": "Categorie di dati",
        "component.none": "Nessuna dichiarazione",
        "capability.local": "No",
        "capability.external": "Sì",
        "capability.undeclared": "Non dichiarato",
        "issues.title": "Problemi e informazioni mancanti",
        "issues.none": "Non sono stati rilevati problemi nella policy di rete.",
        "issue.capability_undeclared": "Capacità non dichiarata",
        "issue.configured_but_unavailable": "Configurato ma non disponibile",
        "issue.endpoint_undeclared": "Endpoint non dichiarato",
        "issue.invalid_endpoint": "Endpoint non valido o oscurato",
        "issue.policy_conflict": "Conflitto con la policy",
        "issue.invalid_declaration": "Dichiarazione non valida",
        "issue.component_limit": "Limite di sicurezza raggiunto",
        "back.security": "Sicurezza",
        "back.home": "Home",
    },
}


def network_translator(language: str) -> Callable[[str], str]:
    catalog = MESSAGES.get(language, MESSAGES["en"])
    fallback = MESSAGES["en"]

    def translate(key: str) -> str:
        return catalog.get(key, fallback.get(key, key))

    return translate

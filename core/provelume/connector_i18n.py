from __future__ import annotations

CONNECTOR_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.connectors": "Connectors",
        "connectors.eyebrow": "Local connector configuration",
        "connectors.title": "Connector instances",
        "connectors.lead": (
            "Inspect isolated provider, account, endpoint, scope, policy, credential-reference, "
            "cursor and health state. This read-only view never contacts a provider."
        ),
        "connectors.read_only": "Read-only and network-free",
        "connectors.active": "Active instances",
        "connectors.enabled": "Enabled instances",
        "connectors.configured_enabled": "Configured enabled",
        "connectors.effective_enabled": "Effectively enabled",
        "connectors.disabled": "Disabled instances",
        "connectors.removed": "Retained removals",
        "connectors.inventory": "Configured instances",
        "connectors.empty": "No connector instance has been configured.",
        "connectors.sources": "Sources",
        "connectors.source": "Connector Source",
        "connectors.provider": "Provider identity",
        "connectors.account": "Account identity",
        "connectors.endpoint": "Endpoint origin",
        "connectors.definition": "Connector definition",
        "connectors.policy": "Local policy",
        "connectors.network_mode": "Network mode",
        "connectors.effective_network": "Effective network",
        "connectors.authorization": "Authorization mode",
        "connectors.scopes": "Least-privilege scopes",
        "connectors.allowed_origins": "Allowed origins",
        "connectors.credential_reference": "External credential reference",
        "connectors.no_credential": "No credential reference configured",
        "connectors.lifecycle": "Lifecycle",
        "connectors.health": "Health",
        "connectors.cursor": "Cursor state",
        "connectors.cursor_empty": "No cursor has been created; refresh is not implemented.",
        "connectors.last_checked": "Last checked",
        "connectors.never_checked": "Never checked",
        "connectors.external_id": "External Source identity",
        "connectors.source_kind": "Source kind",
        "connectors.documents": "Documents retained",
        "connectors.acquisitions": "Acquisitions retained",
        "connectors.original_boundary": "Original preservation boundary",
        "connectors.original_preserved": (
            "Disabling or removing this configuration never deletes or overwrites an acquired "
            "Original. Removal retains a canonical tombstone for provenance."
        ),
        "connectors.authority": "Authority boundary",
        "connectors.authority_text": (
            "Canonical JSON and acquired Originals remain authoritative. Browser, API and CLI "
            "results are aligned service views; indexes and pages do not own business logic."
        ),
        "connectors.status.active": "Active",
        "connectors.status.disabled": "Disabled",
        "connectors.status.removed": "Removed",
        "connectors.status.not_checked": "Not checked",
        "connectors.status.policy_blocked": "Blocked by Instance policy",
        "connectors.status.parent_disabled": "Parent instance disabled",
        "connectors.status.explicit": "Explicit",
        "connectors.status.configuration_only": "Configuration only",
    },
    "it": {
        "nav.connectors": "Connettori",
        "connectors.eyebrow": "Configurazione locale dei connettori",
        "connectors.title": "Istanze dei connettori",
        "connectors.lead": (
            "Consulta separatamente provider, account, endpoint, scope, policy, riferimento alle "
            "credenziali, cursori e salute. Questa vista in sola lettura non contatta provider."
        ),
        "connectors.read_only": "Sola lettura e senza rete",
        "connectors.active": "Istanze attive",
        "connectors.enabled": "Istanze abilitate",
        "connectors.configured_enabled": "Abilitazione configurata",
        "connectors.effective_enabled": "Abilitazione effettiva",
        "connectors.disabled": "Istanze disabilitate",
        "connectors.removed": "Rimozioni conservate",
        "connectors.inventory": "Istanze configurate",
        "connectors.empty": "Non è stata configurata alcuna istanza di connettore.",
        "connectors.sources": "Fonti",
        "connectors.source": "Fonte del connettore",
        "connectors.provider": "Identità del provider",
        "connectors.account": "Identità dell'account",
        "connectors.endpoint": "Origine dell'endpoint",
        "connectors.definition": "Definizione del connettore",
        "connectors.policy": "Policy locale",
        "connectors.network_mode": "Modalità di rete",
        "connectors.effective_network": "Rete effettiva",
        "connectors.authorization": "Modalità di autorizzazione",
        "connectors.scopes": "Scope a privilegio minimo",
        "connectors.allowed_origins": "Origini consentite",
        "connectors.credential_reference": "Riferimento esterno alle credenziali",
        "connectors.no_credential": "Nessun riferimento alle credenziali configurato",
        "connectors.lifecycle": "Ciclo di vita",
        "connectors.health": "Salute",
        "connectors.cursor": "Stato dei cursori",
        "connectors.cursor_empty": (
            "Non è stato creato alcun cursore; il refresh non è implementato."
        ),
        "connectors.last_checked": "Ultimo controllo",
        "connectors.never_checked": "Mai controllato",
        "connectors.external_id": "Identità esterna della Fonte",
        "connectors.source_kind": "Tipo di Fonte",
        "connectors.documents": "Documenti conservati",
        "connectors.acquisitions": "Acquisizioni conservate",
        "connectors.original_boundary": "Confine di conservazione degli Original",
        "connectors.original_preserved": (
            "La disabilitazione o rimozione di questa configurazione non cancella né sovrascrive "
            "un Original acquisito. La rimozione conserva un tombstone canonico per la provenienza."
        ),
        "connectors.authority": "Confine di autorità",
        "connectors.authority_text": (
            "Il JSON canonico e gli Original acquisiti restano autoritativi. Browser, API e CLI "
            "sono viste allineate del servizio; indici e pagine non possiedono logica esclusiva."
        ),
        "connectors.status.active": "Attiva",
        "connectors.status.disabled": "Disabilitata",
        "connectors.status.removed": "Rimossa",
        "connectors.status.not_checked": "Non controllata",
        "connectors.status.policy_blocked": "Bloccata dalla policy dell'istanza",
        "connectors.status.parent_disabled": "Istanza superiore disabilitata",
        "connectors.status.explicit": "Esplicita",
        "connectors.status.configuration_only": "Solo configurazione",
    },
}

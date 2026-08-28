from __future__ import annotations

ACTIVITY_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.inbox": "Inbox",
        "nav.operations": "Operations",
        "nav.bundles": "Bundles",
        "operations.eyebrow": "Local operational evidence",
        "operations.title": "Operations log",
        "operations.lead": (
            "Review the ordered, path-redacted record of ingestion, Inbox and maintenance "
            "operations performed inside this Instance."
        ),
        "operations.kind": "Operation type",
        "operations.status": "Status",
        "operations.filter": "Apply filters",
        "operations.recent": "Recent operations",
        "operations.empty": "No operations match these filters.",
        "operations.events": "Event timeline",
        "operations.no_events": "No events were recorded for this operation.",
        "operations.summary": "Operation summary",
        "operations.started": "Started",
        "operations.completed": "Completed",
        "operations.related": "Related records",
        "operations.metrics": "Metrics",
        "operations.error": "Error",
        "inbox.eyebrow": "Local capture",
        "inbox.title": "Drop Inbox",
        "inbox.lead": (
            "Copy local files into an Instance-owned Source. Submitted originals are kept "
            "exactly and external files are moved only after a verified commit."
        ),
        "inbox.drop_help": "Place supported files in the Instance-relative folder",
        "inbox.waiting": "Files waiting",
        "inbox.submissions": "Submissions",
        "inbox.completed": "Completed",
        "inbox.attention": "Need attention",
        "inbox.recent": "Recent submissions",
        "inbox.items_completed": "items completed",
        "inbox.empty": "No Inbox submissions have been recorded.",
        "bundles.eyebrow": "Rebuildable document context",
        "bundles.title": "Document bundles",
        "bundles.lead": (
            "Browse versioned Markdown, page maps and bounded assets derived from exact "
            "preserved Originals."
        ),
        "bundles.empty": "No document bundle has been built yet.",
        "bundles.pages": "Pages",
        "bundles.assets": "Assets",
        "bundles.warnings": "Warnings",
        "bundles.markdown": "Normalized Markdown",
        "bundles.page_map": "Page map",
        "bundles.manifest": "Bundle manifest",
        "bundles.source_original": "The exact Original remains authoritative.",
    },
    "it": {
        "nav.inbox": "Inbox",
        "nav.operations": "Operazioni",
        "nav.bundles": "Bundle",
        "operations.eyebrow": "Evidenza operativa locale",
        "operations.title": "Registro operazioni",
        "operations.lead": (
            "Consulta il registro ordinato e privo di percorsi fisici delle operazioni di "
            "acquisizione, Inbox e manutenzione svolte in questa istanza."
        ),
        "operations.kind": "Tipo di operazione",
        "operations.status": "Stato",
        "operations.filter": "Applica filtri",
        "operations.recent": "Operazioni recenti",
        "operations.empty": "Nessuna operazione corrisponde ai filtri.",
        "operations.events": "Sequenza degli eventi",
        "operations.no_events": "Nessun evento registrato per questa operazione.",
        "operations.summary": "Riepilogo operazione",
        "operations.started": "Avviata",
        "operations.completed": "Completata",
        "operations.related": "Record collegati",
        "operations.metrics": "Metriche",
        "operations.error": "Errore",
        "inbox.eyebrow": "Acquisizione locale",
        "inbox.title": "Drop Inbox",
        "inbox.lead": (
            "Copia file locali in una fonte posseduta dall'istanza. Gli originali inviati "
            "sono conservati esattamente e i file esterni vengono spostati solo dopo un "
            "commit verificato."
        ),
        "inbox.drop_help": "Inserisci i file supportati nella cartella relativa all'istanza",
        "inbox.waiting": "File in attesa",
        "inbox.submissions": "Invii",
        "inbox.completed": "Completati",
        "inbox.attention": "Da controllare",
        "inbox.recent": "Invii recenti",
        "inbox.items_completed": "elementi completati",
        "inbox.empty": "Nessun invio Inbox è stato registrato.",
        "bundles.eyebrow": "Contesto documentale ricostruibile",
        "bundles.title": "Bundle documentali",
        "bundles.lead": (
            "Consulta Markdown versionato, mappa delle pagine e asset limitati derivati "
            "dagli Original esatti conservati."
        ),
        "bundles.empty": "Non è ancora stato costruito alcun bundle documentale.",
        "bundles.pages": "Pagine",
        "bundles.assets": "Asset",
        "bundles.warnings": "Avvisi",
        "bundles.markdown": "Markdown normalizzato",
        "bundles.page_map": "Mappa pagine",
        "bundles.manifest": "Manifest del bundle",
        "bundles.source_original": "L'Original esatto rimane l'autorità.",
    },
}

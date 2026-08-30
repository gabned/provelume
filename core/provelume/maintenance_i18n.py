from __future__ import annotations

MAINTENANCE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.maintenance": "Maintenance",
        "maintenance.eyebrow": "Governed derived work",
        "maintenance.title": "Maintenance catalogue",
        "maintenance.lead": (
            "Plan, schedule and inspect bounded local maintenance. Reindex generations are "
            "rebuildable; validation and assurance never repair canonical knowledge."
        ),
        "maintenance.saved": "Maintenance job queued",
        "maintenance.error": "Maintenance action was not queued",
        "maintenance.catalog": "Closed action catalogue",
        "maintenance.available": "Available",
        "maintenance.planned": "Unavailable",
        "maintenance.scope": "Scope",
        "maintenance.authority": "Authority",
        "maintenance.recovery": "Recovery",
        "maintenance.plan": "Dry-run estimate",
        "maintenance.items": "items",
        "maintenance.bytes": "estimated bytes",
        "maintenance.temporary": "temporary bytes required",
        "maintenance.free": "free bytes observed",
        "maintenance.ready": "Preflight ready",
        "maintenance.blocked": "Insufficient temporary space",
        "maintenance.reason.planned_s04": "Planned for the bounded S04 lifecycle slice",
        "maintenance.reason.explicit_target_required": (
            "Requires an explicit operator-selected destination contract"
        ),
        "maintenance.action.search.reindex.full": "Full FTS reindex",
        "maintenance.action.search.reindex.full.description": (
            "Build and atomically activate a complete rebuildable FTS generation."
        ),
        "maintenance.action.search.reindex.incremental": "Incremental FTS reindex",
        "maintenance.action.search.reindex.incremental.description": (
            "Reindex exact changed Version evidence in an isolated generation."
        ),
        "maintenance.action.maintenance.library_rebuild": "Markdown-library rebuild",
        "maintenance.action.maintenance.library_rebuild.description": (
            "Rebuild the disposable Markdown library projection."
        ),
        "maintenance.action.maintenance.source_reconcile": "Source reconciliation",
        "maintenance.action.maintenance.source_reconcile.description": (
            "Compare one Source cursor and lifecycle state with durable evidence."
        ),
        "maintenance.action.maintenance.validate": "Instance validation",
        "maintenance.action.maintenance.validate.description": (
            "Run deep, read-only validation over exact Instance state."
        ),
        "maintenance.action.maintenance.original_assurance": "Original assurance",
        "maintenance.action.maintenance.original_assurance.description": (
            "Verify retained Original bytes and canonical references without repair."
        ),
        "maintenance.action.maintenance.duplicate_scan": "Duplicate scan",
        "maintenance.action.maintenance.duplicate_scan.description": (
            "Refresh review-only exact and probable duplicate evidence."
        ),
        "maintenance.action.maintenance.backup_create": "Verified backup creation",
        "maintenance.action.maintenance.backup_create.description": (
            "Create a verified backup at one explicit operator-selected target."
        ),
        "maintenance.action.maintenance.backup_verify": "Backup verification",
        "maintenance.action.maintenance.backup_verify.description": (
            "Verify one explicit backup target without changing the Instance."
        ),
        "maintenance.run_now": "Queue run now",
        "maintenance.local_only": (
            "Run-now controls are available only in the loopback Browser. Timed policies remain "
            "explicit local CLI actions."
        ),
        "maintenance.recent_jobs": "Recent maintenance jobs",
        "maintenance.no_jobs": "No maintenance job has been journaled.",
        "maintenance.generations": "Reindex generations",
        "maintenance.no_generations": "No durable reindex generation has been recorded.",
        "maintenance.boundary_title": "0.8/S03 safety boundary",
        "maintenance.boundary": (
            "No action performs network traffic, canonical mutation or automatic deletion. "
            "Source reconciliation remains planned for S04; backup actions remain unavailable "
            "until an explicit destination can be bound safely."
        ),
    },
    "it": {
        "nav.maintenance": "Manutenzione",
        "maintenance.eyebrow": "Lavoro derivato governato",
        "maintenance.title": "Catalogo manutenzione",
        "maintenance.lead": (
            "Pianifica, programma e consulta manutenzioni locali limitate. Le generazioni "
            "dell'indice sono ricostruibili; validazione e assurance non riparano mai la "
            "conoscenza canonica."
        ),
        "maintenance.saved": "Job di manutenzione accodato",
        "maintenance.error": "L'azione di manutenzione non è stata accodata",
        "maintenance.catalog": "Catalogo chiuso delle azioni",
        "maintenance.available": "Disponibile",
        "maintenance.planned": "Non disponibile",
        "maintenance.scope": "Ambito",
        "maintenance.authority": "Autorità",
        "maintenance.recovery": "Recupero",
        "maintenance.plan": "Stima dry-run",
        "maintenance.items": "elementi",
        "maintenance.bytes": "byte stimati",
        "maintenance.temporary": "byte temporanei richiesti",
        "maintenance.free": "byte liberi osservati",
        "maintenance.ready": "Preflight pronto",
        "maintenance.blocked": "Spazio temporaneo insufficiente",
        "maintenance.reason.planned_s04": (
            "Pianificata per la slice limitata S04 sul ciclo di vita"
        ),
        "maintenance.reason.explicit_target_required": (
            "Richiede un contratto con destinazione scelta esplicitamente dall'operatore"
        ),
        "maintenance.action.search.reindex.full": "Reindicizzazione FTS completa",
        "maintenance.action.search.reindex.full.description": (
            "Costruisce e attiva atomicamente una generazione FTS completa e ricostruibile."
        ),
        "maintenance.action.search.reindex.incremental": (
            "Reindicizzazione FTS incrementale"
        ),
        "maintenance.action.search.reindex.incremental.description": (
            "Reindicizza l'evidenza esatta delle Version modificate in una generazione isolata."
        ),
        "maintenance.action.maintenance.library_rebuild": (
            "Ricostruzione libreria Markdown"
        ),
        "maintenance.action.maintenance.library_rebuild.description": (
            "Ricostruisce la proiezione eliminabile della libreria Markdown."
        ),
        "maintenance.action.maintenance.source_reconcile": "Riconciliazione Source",
        "maintenance.action.maintenance.source_reconcile.description": (
            "Confronta cursore e stato del ciclo di vita di una Source con evidenza durevole."
        ),
        "maintenance.action.maintenance.validate": "Validazione Instance",
        "maintenance.action.maintenance.validate.description": (
            "Esegue una validazione profonda e di sola lettura sullo stato esatto dell'Instance."
        ),
        "maintenance.action.maintenance.original_assurance": "Assurance degli Original",
        "maintenance.action.maintenance.original_assurance.description": (
            "Verifica byte degli Original e riferimenti canonici senza riparazioni."
        ),
        "maintenance.action.maintenance.duplicate_scan": "Scansione duplicati",
        "maintenance.action.maintenance.duplicate_scan.description": (
            "Aggiorna evidenza di revisione per duplicati esatti e probabili."
        ),
        "maintenance.action.maintenance.backup_create": "Creazione backup verificato",
        "maintenance.action.maintenance.backup_create.description": (
            "Crea un backup verificato in una destinazione scelta esplicitamente dall'operatore."
        ),
        "maintenance.action.maintenance.backup_verify": "Verifica backup",
        "maintenance.action.maintenance.backup_verify.description": (
            "Verifica una destinazione di backup esplicita senza modificare l'Instance."
        ),
        "maintenance.run_now": "Accoda ora",
        "maintenance.local_only": (
            "I controlli Run now sono disponibili solo nel Browser loopback. Le policy "
            "temporizzate restano azioni CLI locali esplicite."
        ),
        "maintenance.recent_jobs": "Job di manutenzione recenti",
        "maintenance.no_jobs": "Non è stato registrato alcun job di manutenzione.",
        "maintenance.generations": "Generazioni dell'indice",
        "maintenance.no_generations": (
            "Non è stata registrata alcuna generazione durevole dell'indice."
        ),
        "maintenance.boundary_title": "Confine di sicurezza 0.8/S03",
        "maintenance.boundary": (
            "Nessuna azione usa la rete, modifica lo stato canonico o cancella automaticamente. "
            "La riconciliazione Source resta pianificata per S04; le azioni di backup restano "
            "indisponibili finché non sarà possibile vincolare in sicurezza una destinazione "
            "esplicita."
        ),
    },
}


__all__ = ["MAINTENANCE_TRANSLATIONS"]

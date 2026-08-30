from __future__ import annotations

SCHEDULER_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.scheduler": "Scheduler",
        "scheduler.eyebrow": "Durable local automation",
        "scheduler.title": "Scheduler & job journal",
        "scheduler.lead": (
            "Inspect explicit policies, bounded local jobs and content-free receipts. "
            "Enabled work runs only while a qualified Provelume runtime is active."
        ),
        "scheduler.runtime_ready": "Local runtime ready",
        "scheduler.next_due": "Next due",
        "scheduler.summary": "Scheduler summary",
        "scheduler.policies": "Policies",
        "scheduler.jobs": "Jobs",
        "scheduler.receipts": "Receipts",
        "scheduler.running": "Running",
        "scheduler.cli_control": "Policy changes require an explicit local CLI action.",
        "scheduler.no_policies": "No scheduler policy has been configured.",
        "scheduler.recent_jobs": "Recent jobs",
        "scheduler.no_jobs": "No scheduler job has been journaled.",
        "scheduler.progress": "Processed / skipped / errors",
        "scheduler.attempt": "Attempt",
        "scheduler.recent_receipts": "Recent terminal receipts",
        "scheduler.no_receipts": "No terminal receipt has been written.",
        "scheduler.no_network_delete": (
            "The receipt declares network use and canonical mutation; automatic deletion "
            "is always false."
        ),
        "scheduler.boundary_title": "0.8/S01–S02 boundary",
        "scheduler.boundary": (
            "Instance validation, derived FTS reindex and exact managed-folder refresh are the "
            "executable job kinds. No schedule can authorize repair, purge, retention deletion "
            "or provider writes."
        ),
    },
    "it": {
        "nav.scheduler": "Scheduler",
        "scheduler.eyebrow": "Automazione locale durevole",
        "scheduler.title": "Scheduler e registro job",
        "scheduler.lead": (
            "Consulta policy esplicite, job locali limitati e ricevute prive di contenuti. "
            "Il lavoro abilitato viene eseguito solo mentre è attivo un runtime Provelume "
            "qualificato."
        ),
        "scheduler.runtime_ready": "Runtime locale pronto",
        "scheduler.next_due": "Prossima esecuzione",
        "scheduler.summary": "Riepilogo scheduler",
        "scheduler.policies": "Policy",
        "scheduler.jobs": "Job",
        "scheduler.receipts": "Ricevute",
        "scheduler.running": "In esecuzione",
        "scheduler.cli_control": (
            "Le modifiche alle policy richiedono un'azione CLI locale esplicita."
        ),
        "scheduler.no_policies": "Non è stata configurata alcuna policy dello scheduler.",
        "scheduler.recent_jobs": "Job recenti",
        "scheduler.no_jobs": "Non è stato registrato alcun job dello scheduler.",
        "scheduler.progress": "Elaborati / saltati / errori",
        "scheduler.attempt": "Tentativo",
        "scheduler.recent_receipts": "Ricevute terminali recenti",
        "scheduler.no_receipts": "Non è stata scritta alcuna ricevuta terminale.",
        "scheduler.no_network_delete": (
            "La ricevuta dichiara uso della rete e mutazione canonica; la cancellazione "
            "automatica è sempre falsa."
        ),
        "scheduler.boundary_title": "Confine 0.8/S01–S02",
        "scheduler.boundary": (
            "Validazione dell'istanza, reindicizzazione FTS derivata e refresh esatto delle "
            "cartelle gestite sono i job eseguibili. Nessuna pianificazione può autorizzare "
            "riparazione, purge, cancellazioni di retention o scritture verso provider."
        ),
    },
}

from __future__ import annotations

QUALIFICATION_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.qualification": "Qualification",
        "qualification.eyebrow": "Provider-neutral observations",
        "qualification.title": "Cross-source qualification",
        "qualification.lead": (
            "Compare explicit Sources without merging Originals, identities, "
            "documents or provenance."
        ),
        "qualification.saved": "Qualification control applied",
        "qualification.error": "Qualification control failed",
        "qualification.local_only": "Mutating controls are available only from loopback.",
        "qualification.matrix": "Closed conformance matrix",
        "qualification.limits": "Limits and claim boundaries",
        "qualification.sources": "Select Sources",
        "qualification.queue": "Queue qualification",
        "qualification.resync": "Reset / resync",
        "qualification.jobs": "Jobs, checkpoints, retry and lease",
        "qualification.no_jobs": "No qualification job has been journaled.",
        "qualification.run": "Run",
        "qualification.retry": "Retry",
        "qualification.cancel": "Cancel",
        "qualification.rebuild": "Rebuild from current inputs",
        "qualification.findings": "Findings",
        "qualification.no_findings": "No finding matches these filters.",
        "qualification.filter": "Filter",
        "qualification.inspect": "Inspect evidence and provenance",
        "qualification.finding": "Finding observation",
        "qualification.evidence": "Sanitized evidence",
        "qualification.provenance": "Provenance and limits",
        "qualification.decision": "Human decision",
        "qualification.history": "Append-only decision history",
        "qualification.action": "Decision action",
        "qualification.actor": "Internal actor ID",
        "qualification.reason": "Sanitized rationale",
        "qualification.submit": "Append decision",
        "qualification.canonical": "Canonical source data remains unchanged",
        "qualification.inert": (
            "Operational views contain internal IDs, hashes, counts and codes only. "
            "No source content, implicit network, provider mutation or automatic merge is used."
        ),
    },
    "it": {
        "nav.qualification": "Qualificazione",
        "qualification.eyebrow": "Osservazioni provider-neutral",
        "qualification.title": "Qualificazione cross-source",
        "qualification.lead": (
            "Confronta Source esplicite senza fondere Original, identità, documenti o provenienza."
        ),
        "qualification.saved": "Controllo di qualificazione applicato",
        "qualification.error": "Controllo di qualificazione non riuscito",
        "qualification.local_only": "I controlli mutativi sono disponibili solo in loopback.",
        "qualification.matrix": "Matrice chiusa di conformità",
        "qualification.limits": "Limiti e confini dei claim",
        "qualification.sources": "Seleziona le Source",
        "qualification.queue": "Accoda qualificazione",
        "qualification.resync": "Azzera / risincronizza",
        "qualification.jobs": "Job, checkpoint, retry e lease",
        "qualification.no_jobs": "Nessun job di qualificazione è stato registrato.",
        "qualification.run": "Esegui",
        "qualification.retry": "Riprova",
        "qualification.cancel": "Annulla",
        "qualification.rebuild": "Ricostruisci dagli input correnti",
        "qualification.findings": "Finding",
        "qualification.no_findings": "Nessun finding corrisponde ai filtri.",
        "qualification.filter": "Filtra",
        "qualification.inspect": "Ispeziona evidenze e provenienza",
        "qualification.finding": "Osservazione del finding",
        "qualification.evidence": "Evidenza sanitizzata",
        "qualification.provenance": "Provenienza e limiti",
        "qualification.decision": "Decisione umana",
        "qualification.history": "Cronologia append-only delle decisioni",
        "qualification.action": "Azione della decisione",
        "qualification.actor": "ID interno dell'autore",
        "qualification.reason": "Motivazione sanitizzata",
        "qualification.submit": "Aggiungi decisione",
        "qualification.canonical": "I dati sorgente canonici restano invariati",
        "qualification.inert": (
            "Le viste operative contengono solo ID interni, hash, conteggi e codici. "
            "Non sono usati contenuto sorgente, rete implicita, mutazioni provider "
            "o merge automatici."
        ),
    },
}

__all__ = ["QUALIFICATION_TRANSLATIONS"]

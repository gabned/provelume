from __future__ import annotations

OCR_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.ocr": "Local OCR",
        "ocr.eyebrow": "Optional derived processing",
        "ocr.title": "Local OCR",
        "ocr.lead": (
            "Run bounded OCR with explicitly installed local components. OCR text is "
            "machine-unverified derived state, never canonical knowledge."
        ),
        "ocr.saved": "OCR control applied",
        "ocr.error": "OCR control failed",
        "ocr.local_only": "Mutating controls are available only from the loopback browser.",
        "ocr.capability": "Effective capability",
        "ocr.state": "State",
        "ocr.available": "Available",
        "ocr.engine": "Engine",
        "ocr.renderer": "Renderer and decoder",
        "ocr.languages": "Installed languages",
        "ocr.limits": "Effective OCR limits",
        "ocr.configure": "Explicit configuration",
        "ocr.mode": "Mode",
        "ocr.selected_languages": "Language packs (comma separated)",
        "ocr.executable": "Tesseract executable",
        "ocr.tessdata": "Optional tessdata directory",
        "ocr.dpi": "Render DPI",
        "ocr.save": "Save OCR configuration",
        "ocr.queue": "Queue one DocumentVersion",
        "ocr.version": "DocumentVersion ID",
        "ocr.pages": "Selected pages (comma separated)",
        "ocr.queue_action": "Queue OCR",
        "ocr.jobs": "Durable OCR jobs",
        "ocr.no_jobs": "No OCR job has been journaled.",
        "ocr.cancel": "Cancel",
        "ocr.bundles": "Verified derived bundles",
        "ocr.no_bundles": "No OCR bundle is present.",
        "ocr.remove": "Remove derived OCR",
        "ocr.rebuild": "Remove and rebuild",
        "ocr.boundary": (
            "No cloud, runtime download or remote fallback is used. The base package "
            "contains no OCR engine, renderer or language pack."
        ),
    },
    "it": {
        "nav.ocr": "OCR locale",
        "ocr.eyebrow": "Elaborazione derivata opzionale",
        "ocr.title": "OCR locale",
        "ocr.lead": (
            "Esegue OCR limitato con componenti locali installati esplicitamente. Il testo "
            "OCR è uno stato derivato non verificato dalla macchina, mai conoscenza canonica."
        ),
        "ocr.saved": "Controllo OCR applicato",
        "ocr.error": "Controllo OCR non riuscito",
        "ocr.local_only": "I controlli di modifica sono disponibili solo nel browser loopback.",
        "ocr.capability": "Capability effettiva",
        "ocr.state": "Stato",
        "ocr.available": "Disponibile",
        "ocr.engine": "Motore",
        "ocr.renderer": "Renderer e decoder",
        "ocr.languages": "Lingue installate",
        "ocr.limits": "Limiti OCR effettivi",
        "ocr.configure": "Configurazione esplicita",
        "ocr.mode": "Modalità",
        "ocr.selected_languages": "Language pack (separati da virgola)",
        "ocr.executable": "Eseguibile Tesseract",
        "ocr.tessdata": "Directory tessdata opzionale",
        "ocr.dpi": "DPI di rendering",
        "ocr.save": "Salva configurazione OCR",
        "ocr.queue": "Accoda una DocumentVersion",
        "ocr.version": "ID DocumentVersion",
        "ocr.pages": "Pagine selezionate (separate da virgola)",
        "ocr.queue_action": "Accoda OCR",
        "ocr.jobs": "Job OCR durevoli",
        "ocr.no_jobs": "Nessun job OCR è stato registrato.",
        "ocr.cancel": "Annulla",
        "ocr.bundles": "Bundle derivati verificati",
        "ocr.no_bundles": "Non è presente alcun bundle OCR.",
        "ocr.remove": "Rimuovi OCR derivato",
        "ocr.rebuild": "Rimuovi e ricostruisci",
        "ocr.boundary": (
            "Non vengono usati cloud, download a runtime o fallback remoto. Il pacchetto base "
            "non contiene motore OCR, renderer o language pack."
        ),
    },
}


__all__ = ["OCR_TRANSLATIONS"]

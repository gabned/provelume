"Editor interface labels; generated product translations are not human review."

LABELS = {
    "en": {
        "title": "Correct OCR and transcripts",
        "lead": "Review the evidence, then save an attributed annotation.",
        "notice": (
            "Original bytes and engine output stay unchanged. Speaker labels are "
            "proposals, not verified identities."
        ),
        "empty": "No supported anchored result is available.",
        "partial": "The evidence inventory is incomplete.",
        "open": "Open editor",
        "evidence": "Original evidence",
        "text": "Editable text",
        "confidence": "Confidence",
        "unknown": "Unknown confidence",
        "previous": "Previous uncertain segment",
        "next": "Next uncertain segment",
        "apply": "Preview text change",
        "speaker": "Proposed speaker label",
        "speaker_apply": "Preview speaker proposal",
        "merge": "Merge with next segment",
        "split": "Split at text cursor",
        "save": "Save reviewed changes",
        "preview": "Before and after",
        "before": "Before",
        "after": "After",
        "history": "Retained history",
        "undo": "Preview undo to selected revision",
        "original": "Original engine result",
        "revision": "Revision",
        "unavailable": (
            "Evidence is unavailable or changed. Saving is disabled; retained history is preserved."
        ),
        "media_unavailable": "Playable media was not attested for this result.",
        "shared": (
            "Split segments share original anchors; no new timing or coordinates are inferred."
        ),
        "disabled": "Saving is disabled by the current capability policy.",
        "configure": "Review capability settings",
        "fresh": "Open a fresh review",
        "saved": "Annotation saved. Open a fresh review to continue.",
        "error": (
            "Operation unavailable or outcome unconfirmed. Check history and recovery "
            "before a new review; your draft remains visible."
        ),
        "dirty": "Unsaved draft. Preview every changed segment before saving.",
        "ready": "Preview ready. Saving appends one retained revision.",
        "noscript": "This synchronized editor requires its local script.",
        "page": "Page",
        "region": "Region",
        "width": "width",
        "height": "height",
        "time": "Time",
        "anchor": "Source anchor",
        "version": "Version",
        "result": "Result digest",
    },
    "it": {
        "title": "Correggi OCR e trascrizioni",
        "lead": "Controlla le evidenze, poi salva un'annotazione attribuita.",
        "notice": (
            "I byte originali e l'output del motore restano invariati. Le etichette "
            "dei parlanti sono proposte, non identità verificate."
        ),
        "empty": "Nessun risultato supportato con riferimenti è disponibile.",
        "partial": "L'inventario delle evidenze è incompleto.",
        "open": "Apri editor",
        "evidence": "Evidenza originale",
        "text": "Testo modificabile",
        "confidence": "Confidenza",
        "unknown": "Confidenza sconosciuta",
        "previous": "Segmento incerto precedente",
        "next": "Segmento incerto successivo",
        "apply": "Anteprima modifica del testo",
        "speaker": "Etichetta proposta del parlante",
        "speaker_apply": "Anteprima proposta parlante",
        "merge": "Unisci al segmento successivo",
        "split": "Dividi al cursore del testo",
        "save": "Salva modifiche revisionate",
        "preview": "Prima e dopo",
        "before": "Prima",
        "after": "Dopo",
        "history": "Cronologia conservata",
        "undo": "Anteprima ripristino della revisione selezionata",
        "original": "Risultato originale del motore",
        "revision": "Revisione",
        "unavailable": (
            "L'evidenza non è disponibile o è cambiata. Il salvataggio è "
            "disabilitato; la cronologia è conservata."
        ),
        "media_unavailable": (
            "Per questo risultato non è stata attestata la disponibilità del "
            "contenuto multimediale."
        ),
        "shared": (
            "I segmenti divisi condividono i riferimenti originali; non sono dedotti "
            "nuovi tempi o coordinate."
        ),
        "disabled": "Il salvataggio è disabilitato dalla policy corrente della capacità.",
        "configure": "Impostazioni delle capacità di revisione",
        "fresh": "Apri una nuova revisione",
        "saved": "Annotazione salvata. Apri una nuova revisione per continuare.",
        "error": (
            "Operazione non disponibile o esito non confermato. Controlla cronologia "
            "e ripristino prima di una nuova revisione; la bozza resta visibile."
        ),
        "dirty": (
            "Bozza non salvata. Visualizza l'anteprima di ogni segmento modificato "
            "prima di salvare."
        ),
        "ready": "Anteprima pronta. Il salvataggio aggiunge una revisione conservata.",
        "noscript": "L'editor sincronizzato richiede il suo script locale.",
        "page": "Pagina",
        "region": "Regione",
        "width": "larghezza",
        "height": "altezza",
        "time": "Tempo",
        "anchor": "Riferimento originale",
        "version": "Versione",
        "result": "Digest del risultato",
    },
}


def annotation_labels(language: str) -> dict[str, str]:
    return dict(LABELS.get(language, LABELS["en"]))

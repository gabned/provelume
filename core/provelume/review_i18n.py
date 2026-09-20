"""English and Italian labels for retained domain review flows."""

REVIEW_TRANSLATIONS = {
    "en": {
        "review.committed": "Confirmed domain effect",
        "review.inspection_state": "Evidence inspection state",
        "review.recorded_scope": (
            "These receipts record committed effects. "
            "Request a fresh preview to verify current inputs and permissions."
        ),
        "review.history_bound": "Showing the latest 50 receipts from the bounded history view.",
        "review.open_decision": "Review the proposed change",
        "review.corrections": "Correct OCR or transcript",
        "review.capabilities": "Review permissions",
        "review.title": "Review a change",
        "review.lead": (
            "Choose the intended change, inspect its effects, then confirm the exact preview."
        ),
        "review.placement": "Area and Project placement",
        "review.routing": "Routing rules",
        "review.duplicates": "Duplicate review",
        "review.versions": "Version conflict",
        "review.annotations": "OCR and transcript corrections",
        "review.configure": "Change permission",
        "review.classify": "Set placement",
        "review.save_rule": "Save routing rule",
        "review.revoke_rule": "Revoke routing rule",
        "review.apply_rule": "Apply selected rule",
        "review.routing_empty_title": "No routing action available",
        "review.routing_empty_help": (
            "No applicable routing action is available for this document in the current view. "
            "You can review its placement manually or inspect the routing rules."
        ),
        "review.link_exact": "Link exact occurrences",
        "review.relate": "Keep as related Documents",
        "review.keep_separate": "Keep Documents separate",
        "review.new_version": "Create a reviewed Version on the target",
        "review.select_current": "Select an existing target Version",
        "review.save": "Save corrections",
        "review.undo": "Restore an earlier correction revision",
        "review.disabled": "Disabled",
        "review.proposal-only": "Proposals only",
        "review.confirm-each": "Confirm every change",
        "review.controlled-automatic": "Automatic safe routing",
        "review.permission_denied": (
            "This permission currently prevents confirmation. You can inspect a preview and "
            "configure an explicit permission."
        ),
        "review.action": "Intended change",
        "review.primary": "Primary Area or Project",
        "review.secondary": "Secondary associations",
        "review.multi_help": (
            "Use Ctrl (or Command) to select multiple entries. No selection means none."
        ),
        "review.source": "Source",
        "review.path_prefix": "Relative path prefix",
        "review.path_help": (
            "A literal path such as invoices/2026. Empty means this whole Source. No wildcards or"
            " absolute paths."
        ),
        "review.automatic": "Allow this rule to be considered for automatic routing",
        "review.automatic_help": (
            "Only unclassified Documents with one matching rule and a separate automatic routing "
            "permission can be changed automatically."
        ),
        "review.rule": "Routing rule",
        "review.target": "Target Document",
        "review.version": "Version to use",
        "review.version_help": (
            "Creating a reviewed Version retains the selected Original and every prior identity. "
            "Selecting current requires a Version already owned by the target."
        ),
        "review.mode": "Permission mode",
        "review.actions": "Allowed changes",
        "review.all_subjects": "Apply to every supported object, including future objects",
        "review.subjects": "Specific objects",
        "review.sources": "Restrict to Sources",
        "review.sources_help": (
            "No Source selection means no Source restriction. Source restrictions apply to "
            "Document subjects; create a rule before restricting its applications."
        ),
        "review.scope_help": (
            "A permission does not apply an effect. Automatic mode only supports routing "
            "application; all other changes remain manual."
        ),
        "review.preview": "Preview change",
        "review.confirm": "Confirm this exact change",
        "review.confirm_check": "I have reviewed the effect and its reversibility.",
        "review.preview_title": "Before you confirm",
        "review.before": "Before",
        "review.after": "After",
        "review.impact": "Effect",
        "review.reversibility": "Reversibility",
        "review.confidence": "Confidence",
        "review.unknown": "Unknown",
        "review.none": "None",
        "review.yes": "Yes",
        "review.no": "No",
        "review.evidence": "Bound evidence and hashes",
        "review.history": "Retained decision history",
        "review.history_empty": "No recorded domain decisions for this object.",
        "review.history_refresh": (
            "This history was loaded before the confirmation attempt. "
            "Open a fresh view to check retained decisions."
        ),
        "review.incomplete": (
            "This view is incomplete or unavailable. Do not interpret it as an empty history."
        ),
        "review.fresh": "Open a fresh review",
        "review.saved": "Change committed with its retained receipt.",
        "review.changed": "Your selection changed. Request a new preview before confirming.",
        "review.error": (
            "The change was not confirmed. Inputs, permissions or availability may have changed; "
            "open a fresh review."
        ),
        "review.uncertain": (
            "The confirmation response is unavailable. Open a fresh review and check retained "
            "history before making another decision."
        ),
        "review.from_version": "New reviewed Version from",
        "review.loading": "Checking the current evidence…",
        "review.unavailable": (
            "The required evidence is unavailable, invalid or exceeds the view's bound."
        ),
        "review.new_rule": "Create a routing rule",
        "review.rules_empty": "No retained routing rules.",
        "review.enabled": "Enabled",
        "review.revoked": "Revoked",
        "review.revision": "Revision",
        "review.back": "Action Center",
        "review.noscript": (
            "Enable JavaScript for the preview and one-use confirmation controls. No changes have"
            " been made."
        ),
        "review.effect_placement": (
            "Update classification while preserving Original, Versions and prior provenance edges."
        ),
        "review.reverse_placement": (
            "A later review can restore prior destinations. The decision history remains."
        ),
        "review.reverse_first_placement": (
            "A later review can change placement. Returning to unclassified is not supported."
        ),
        "review.effect_rule": (
            "Save or revoke a revisioned rule for later Documents and acquisitions. This does not"
            " classify existing Documents."
        ),
        "review.reverse_rule": (
            "Edit or revoke the rule with a new review; earlier applications and history remain."
        ),
        "review.effect_relation": (
            "Record the chosen relationship while preserving all Documents, Versions, Sources and"
            " Originals."
        ),
        "review.reverse_relation": (
            "A later reviewed relationship can supersede this one; history remains."
        ),
        "review.effect_version": (
            "Change the target's current Version while retaining every prior identity and Original."
        ),
        "review.reverse_version": (
            "A later confirmed Version choice can restore the earlier current Version; history "
            "remains."
        ),
        "review.effect_permission": (
            "Change which future operations are allowed in the selected scope. No domain effect "
            "is applied now."
        ),
        "review.reverse_permission": (
            "A new confirmed permission can revoke access. Already committed effects retain their"
            " history."
        ),
        "review.ambiguous": (
            "Several rules match. This selection requires explicit confirmation and cannot run "
            "automatically."
        ),
    },
    "it": {
        "review.committed": "Effetto di dominio confermato",
        "review.inspection_state": "Stato dell'esame delle evidenze",
        "review.recorded_scope": (
            "Queste ricevute registrano effetti applicati. "
            "Richiedi una nuova anteprima per verificare evidenze e permessi attuali."
        ),
        "review.history_bound": (
            "Sono mostrate le ultime 50 ricevute della vista di cronologia limitata."
        ),
        "review.open_decision": "Rivedi la modifica proposta",
        "review.corrections": "Correggi OCR o trascrizione",
        "review.capabilities": "Permessi di revisione",
        "review.title": "Rivedi una modifica",
        "review.lead": "Scegli la modifica, verifica gli effetti e conferma l'anteprima esatta.",
        "review.placement": "Collocazione in Aree e Progetti",
        "review.routing": "Regole di instradamento",
        "review.duplicates": "Revisione duplicati",
        "review.versions": "Conflitto tra Versioni",
        "review.annotations": "Correzioni OCR e trascrizioni",
        "review.configure": "Modifica permesso",
        "review.classify": "Imposta collocazione",
        "review.save_rule": "Salva regola di instradamento",
        "review.revoke_rule": "Revoca regola di instradamento",
        "review.apply_rule": "Applica la regola selezionata",
        "review.routing_empty_title": "Nessuna azione di instradamento disponibile",
        "review.routing_empty_help": (
            "Nella vista corrente non è disponibile un'azione di instradamento applicabile "
            "a questo documento. Puoi rivedere manualmente la collocazione o consultare le regole."
        ),
        "review.link_exact": "Collega occorrenze identiche",
        "review.relate": "Mantieni Documenti correlati",
        "review.keep_separate": "Mantieni Documenti separati",
        "review.new_version": "Crea una Versione revisionata nel destinatario",
        "review.select_current": "Seleziona una Versione già del destinatario",
        "review.save": "Salva correzioni",
        "review.undo": "Ripristina una revisione precedente delle correzioni",
        "review.disabled": "Disabilitato",
        "review.proposal-only": "Solo proposte",
        "review.confirm-each": "Conferma ogni modifica",
        "review.controlled-automatic": "Instradamento sicuro automatico",
        "review.permission_denied": (
            "Il permesso attuale impedisce la conferma. Puoi verificare l'anteprima e configurare"
            " un permesso esplicito."
        ),
        "review.action": "Modifica desiderata",
        "review.primary": "Area o Progetto primario",
        "review.secondary": "Associazioni secondarie",
        "review.multi_help": (
            "Usa Ctrl (o Command) per selezionare più voci. Nessuna selezione significa nessuna "
            "associazione."
        ),
        "review.source": "Sorgente",
        "review.path_prefix": "Prefisso del percorso relativo",
        "review.path_help": (
            "Un percorso letterale, ad esempio fatture/2026. Vuoto significa tutta la Sorgente. "
            "Niente caratteri jolly o percorsi assoluti."
        ),
        "review.automatic": "Consenti di considerare questa regola per l'instradamento automatico",
        "review.automatic_help": (
            "Solo Documenti non classificati, con una sola regola corrispondente e un permesso "
            "automatico separato, possono essere modificati automaticamente."
        ),
        "review.rule": "Regola di instradamento",
        "review.target": "Documento destinatario",
        "review.version": "Versione da utilizzare",
        "review.version_help": (
            "Una Versione revisionata conserva l'Originale selezionato e tutte le identità "
            "precedenti. La selezione corrente richiede una Versione già appartenente al "
            "destinatario."
        ),
        "review.mode": "Modalità del permesso",
        "review.actions": "Modifiche consentite",
        "review.all_subjects": "Applica a tutti gli oggetti supportati, inclusi quelli futuri",
        "review.subjects": "Oggetti specifici",
        "review.sources": "Limita alle Sorgenti",
        "review.sources_help": (
            "Nessuna Sorgente selezionata significa nessuna restrizione di Sorgente. La "
            "restrizione si applica ai Documenti; crea la regola prima di limitarne le "
            "applicazioni."
        ),
        "review.scope_help": (
            "Un permesso non applica modifiche. La modalità automatica supporta solo "
            "l'applicazione di regole; le altre modifiche restano manuali."
        ),
        "review.preview": "Anteprima della modifica",
        "review.confirm": "Conferma questa modifica esatta",
        "review.confirm_check": "Ho verificato l'effetto e la sua reversibilità.",
        "review.preview_title": "Prima della conferma",
        "review.before": "Prima",
        "review.after": "Dopo",
        "review.impact": "Effetto",
        "review.reversibility": "Reversibilità",
        "review.confidence": "Confidenza",
        "review.unknown": "Sconosciuta",
        "review.none": "Nessuno",
        "review.yes": "Sì",
        "review.no": "No",
        "review.evidence": "Evidenze e hash vincolati",
        "review.history": "Cronologia delle decisioni conservate",
        "review.history_empty": "Nessuna decisione di dominio registrata per questo oggetto.",
        "review.history_refresh": (
            "Questa cronologia è stata caricata prima del tentativo di conferma. "
            "Apri una vista aggiornata per verificare le decisioni conservate."
        ),
        "review.incomplete": (
            "Questa vista è incompleta o non disponibile. Non interpretarla come una cronologia "
            "vuota."
        ),
        "review.fresh": "Apri una nuova revisione",
        "review.saved": "Modifica applicata insieme alla ricevuta conservata.",
        "review.changed": (
            "La selezione è cambiata. Richiedi una nuova anteprima prima di confermare."
        ),
        "review.error": (
            "La modifica non è stata confermata. Evidenze, permessi o disponibilità potrebbero "
            "essere cambiati; apri una nuova revisione."
        ),
        "review.uncertain": (
            "La risposta alla conferma non è disponibile. Apri una nuova revisione e verifica la "
            "cronologia conservata prima di un'altra decisione."
        ),
        "review.from_version": "Nuova Versione revisionata da",
        "review.loading": "Verifica delle evidenze attuali…",
        "review.unavailable": (
            "Le evidenze necessarie non sono disponibili, sono invalide o superano il limite "
            "della vista."
        ),
        "review.new_rule": "Crea una regola di instradamento",
        "review.rules_empty": "Nessuna regola di instradamento conservata.",
        "review.enabled": "Attiva",
        "review.revoked": "Revocata",
        "review.revision": "Revisione",
        "review.back": "Centro azioni",
        "review.noscript": (
            "Abilita JavaScript per anteprima e conferma monouso. Nessuna modifica è stata "
            "applicata."
        ),
        "review.effect_placement": (
            "Aggiorna la classificazione conservando Originale, Versioni e collegamenti di "
            "provenienza precedenti."
        ),
        "review.reverse_placement": (
            "Una revisione successiva può ripristinare le destinazioni precedenti. La cronologia "
            "rimane."
        ),
        "review.reverse_first_placement": (
            "Una revisione successiva può cambiare collocazione. Il ritorno a non classificato "
            "non è supportato."
        ),
        "review.effect_rule": (
            "Salva o revoca una regola revisionata per Documenti e acquisizioni successive. Non "
            "classifica i Documenti esistenti."
        ),
        "review.reverse_rule": (
            "Modifica o revoca la regola con una nuova revisione; applicazioni precedenti e "
            "cronologia rimangono."
        ),
        "review.effect_relation": (
            "Registra la relazione scelta conservando tutti i Documenti, le Versioni, le Sorgenti"
            " e gli Originali."
        ),
        "review.reverse_relation": (
            "Una relazione revisionata successiva può sostituire questa; la cronologia rimane."
        ),
        "review.effect_version": (
            "Cambia la Versione corrente del destinatario conservando tutte le identità e gli "
            "Originali precedenti."
        ),
        "review.reverse_version": (
            "Una scelta di Versione confermata successiva può ripristinare la corrente "
            "precedente; la cronologia rimane."
        ),
        "review.effect_permission": (
            "Cambia le operazioni future consentite nell'ambito selezionato. Non applica ora "
            "modifiche di dominio."
        ),
        "review.reverse_permission": (
            "Un nuovo permesso confermato può revocare l'accesso. Le modifiche già applicate "
            "conservano la cronologia."
        ),
        "review.ambiguous": (
            "Corrispondono più regole. Questa scelta richiede conferma esplicita e non può essere"
            " automatica."
        ),
    },
}


def review_labels(language: str) -> dict[str, str]:
    selected = REVIEW_TRANSLATIONS.get(language, REVIEW_TRANSLATIONS["en"])
    return {key.removeprefix("review."): value for key, value in selected.items()}

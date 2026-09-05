from __future__ import annotations

_TEXT = {
    "title": ("Source exclusions", "Esclusioni della Source"),
    "lead": (
        "Choose what future filesystem intake may read. Previously acquired records are retained.",
        "Scegli cosa possono leggere le acquisizioni future. I record già acquisiti "
        "restano conservati.",
    ),
    "revision": ("Rule version", "Versione delle regole"),
    "enabled": ("Enabled", "Abilitate"),
    "disabled": ("Disabled", "Disabilitate"),
    "state": ("All rules", "Tutte le regole"),
    "rule_state": ("Rule state", "Stato della regola"),
    "kind": ("Kind", "Tipo"),
    "pattern": ("Relative pattern or extension/type", "Pattern relativo o estensione/tipo"),
    "action": ("Effect", "Effetto"),
    "exclude": ("Exclude", "Escludi"),
    "include": ("Explicitly include (override)", "Includi esplicitamente (override)"),
    "subfolder": ("Subfolder", "Sottocartella"),
    "file": ("Exact file", "File esatto"),
    "extension": ("Extension", "Estensione"),
    "type": ("File type", "Tipo di file"),
    "glob": ("Portable glob", "Glob portabile"),
    "preview": ("Preview change", "Anteprima della modifica"),
    "inspect": ("Preview ingestion", "Anteprima delle acquisizioni"),
    "defaults": ("Preview safe defaults", "Anteprima dei default sicuri"),
    "remove": ("Preview removal", "Anteprima della rimozione"),
    "apply": ("Apply this preview", "Applica questa anteprima"),
    "add": ("Add a rule", "Aggiungi una regola"),
    "rules": ("Current rules", "Regole correnti"),
    "proposed": ("Proposed rules", "Regole proposte"),
    "saved": (
        "Rules applied. Acquired Originals and canonical records were retained.",
        "Regole applicate. Originals acquisiti e record canonici sono stati conservati.",
    ),
    "preview_ready": (
        "Preview ready. No rule or acquired record has changed.",
        "Anteprima pronta. Nessuna regola o record acquisito è stato modificato.",
    ),
    "counts": ("Preview counts", "Conteggi dell'anteprima"),
    "entries": ("Entries checked", "Voci verificate"),
    "included_files": ("Files eligible for intake", "File ammessi all'acquisizione"),
    "excluded_files": ("Excluded files inspected", "File esaminati ed esclusi"),
    "excluded_directories": (
        "Excluded subfolders, not scanned",
        "Sottocartelle escluse, non scandite",
    ),
    "unsupported_files": ("Unsupported file types", "Tipi di file non supportati"),
    "included_bytes": ("Eligible bytes", "Byte ammessi"),
    "unfollowed_links": ("Directory links not followed", "Link a cartelle non seguiti"),
    "count_help": (
        "Files inside excluded subfolders are not enumerated or included in file counts. "
        "An explicit include can override an exclusion and require checking that subtree.",
        "I file nelle sottocartelle escluse non sono enumerati né inclusi nei conteggi dei file. "
        "Un'inclusione esplicita può superare un'esclusione e richiedere la verifica "
        "della sottocartella.",
    ),
    "reason": ("Reason", "Motivo"),
    "locator": ("Source-relative name", "Nome relativo alla Source"),
    "truncated": (
        "Only the first 200 reasons are shown; counts cover the complete bounded preview.",
        "Sono mostrati solo i primi 200 motivi; i conteggi coprono l'intera anteprima limitata.",
    ),
    "help": (
        "Paths are case-sensitive and Unicode-normalized; extensions and file types ignore case. "
        "Use * or ? within one component and ** across folders. Maximum: 32 rules, 256 characters "
        "and 16 components per pattern. File types: text, document, image, audio, video, "
        "email, archive.",
        "I percorsi distinguono maiuscole e minuscole e sono normalizzati Unicode; "
        "estensioni e tipi "
        "ignorano le maiuscole. Usa * o ? in un componente e ** tra cartelle. Limiti: 32 regole, "
        "256 caratteri e 16 componenti per pattern. Tipi: text, document, image, audio, "
        "video, email, archive.",
    ),
    "reason.included": ("Included", "Incluso"),
    "reason.excluded": ("Excluded by rule", "Escluso dalla regola"),
    "reason.explicit_override": (
        "Explicit inclusion overrides exclusions",
        "L'inclusione esplicita supera le esclusioni",
    ),
    "reason.rules_disabled": ("Rules disabled", "Regole disabilitate"),
    "reason.unsupported_type": ("No supported extractor", "Nessun estrattore supportato"),
    "reason.directory_link_not_followed": (
        "Directory links are not followed",
        "I link a cartelle non sono seguiti",
    ),
}
ERROR_TEXT = {
    "invalid_rules": (
        "Check the rule kind, relative pattern and limits; duplicate or unsupported "
        "rules are rejected.",
        "Controlla tipo, pattern relativo e limiti; le regole duplicate o non supportate "
        "sono rifiutate.",
    ),
    "preview_limit": (
        "The preview exceeded its file, entry, depth or time limit. Select a narrower "
        "Source or a simpler rule.",
        "L'anteprima ha superato il limite di file, voci, profondità o tempo. Scegli una "
        "Source più ristretta o una regola più semplice.",
    ),
    "preview_busy": (
        "Two filesystem previews are still pending. Wait for them to finish before retrying.",
        "Sono ancora in corso due anteprime filesystem. Attendi che terminino prima di riprovare.",
    ),
    "preview_timeout": (
        "The filesystem did not answer within five seconds. Check the mount and retry explicitly.",
        "Il filesystem non ha risposto entro cinque secondi. Controlla il mount e "
        "riprova esplicitamente.",
    ),
    "preview_unavailable": (
        "The Source cannot be safely read. Check reachability, permissions and symbolic "
        "links, then retry.",
        "La Source non può essere letta in sicurezza. Controlla raggiungibilità, "
        "permessi e link simbolici, quindi riprova.",
    ),
    "version_conflict": (
        "The rules changed. Reload the current version and preview your change again.",
        "Le regole sono cambiate. Ricarica la versione corrente e ripeti l'anteprima "
        "della modifica.",
    ),
    "stale_preview": (
        "The Source or proposed rules no longer match this preview. Preview the change "
        "again before applying it.",
        "La Source o le regole proposte non corrispondono più all'anteprima. Ripeti "
        "l'anteprima prima di applicare la modifica.",
    ),
}
EXCLUSION_TRANSLATIONS = {
    language: {"exclusions." + key: pair[index] for key, pair in _TEXT.items()}
    for index, language in enumerate(("en", "it"))
}


def exclusion_message(code: str, language: str = "en") -> str:
    return ERROR_TEXT.get(code, ERROR_TEXT["invalid_rules"])[language == "it"]

from __future__ import annotations

from collections.abc import Callable

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "nav.security": "Security",
        "nav.verify_installation": "Verify installation",
        "nav.verify_description": "Check installed package files locally without network access.",
        "title": "Verify installation",
        "intro": (
            "Check the installed Provelume package files locally. This verification uses "
            "no network and never reads Instance knowledge or personal configuration."
        ),
        "status.package_integrity_verified": "Package integrity verified",
        "status.modified_installation": "Modified installation",
        "status.verification_unavailable": "Verification unavailable",
        "reason.package_integrity_verified": (
            "All hashed package files match wheel RECORD."
        ),
        "reason.modified_installation": (
            "Installed package files differ from wheel RECORD."
        ),
        "reason.verification_unavailable": (
            "Package metadata or the imported-package binding is insufficient for a "
            "complete integrity result."
        ),
        "label.package": "Package",
        "label.version": "Version",
        "label.checked": "Files checked",
        "label.tracked": "Files tracked",
        "label.unhashed": "Unhashed records",
        "label.unexpected": "Unexpected files",
        "label.network": "Network used",
        "label.origin": "Official origin",
        "network.none": "No",
        "origin.not_established": "Not established by local package metadata",
        "findings.title": "Findings",
        "findings.none": "No package-file integrity problems were found.",
        "findings.unavailable": (
            "No complete finding set is available because verification did not complete."
        ),
        "findings.truncated": "Additional findings were omitted at the safety limit.",
        "issue.missing_file": "Missing file",
        "issue.modified_file": "Modified file",
        "issue.unreadable_file": "Unreadable file",
        "issue.unreadable_path": "Unreadable package path",
        "issue.unexpected_file": "Unexpected package file",
        "issue.unsafe_path": "Unsafe path or symbolic link",
        "issue.unhashed_record": "Unhashed RECORD entry",
        "issue.unsupported_hash": "Unsupported hash",
        "issue.invalid_record": "Invalid RECORD entry",
        "issue.scan_limit": "Safety limit reached",
        "detail.missing_file": "A file declared by wheel RECORD is missing.",
        "detail.modified_file": "The installed file differs from wheel RECORD.",
        "detail.unreadable_file": "The installed file could not be read completely.",
        "detail.unreadable_path": "The package path could not be scanned completely.",
        "detail.unexpected_file": (
            "A package file is present but is not declared by wheel RECORD."
        ),
        "detail.unsafe_path": (
            "The path is unsafe or contains a symbolic link or filesystem reparse point."
        ),
        "detail.unhashed_record": (
            "Wheel RECORD does not provide a cryptographic hash for this file."
        ),
        "detail.unsupported_hash": "The RECORD hash algorithm is not supported.",
        "detail.invalid_record": "The RECORD hash is malformed or noncanonical.",
        "detail.scan_limit": "Verification reached its processing safety limit.",
        "explain.integrity": (
            "A matching wheel RECORD shows that installed package bytes have not changed "
            "since this distribution was installed."
        ),
        "explain.origin": (
            "A self-consistent wheel can still be unofficial. Official-origin verification "
            "requires a trusted release manifest, signature or attestation."
        ),
        "back.home": "Home",
    },
    "it": {
        "nav.security": "Sicurezza",
        "nav.verify_installation": "Verifica installazione",
        "nav.verify_description": (
            "Controlla localmente i file installati senza usare la rete."
        ),
        "title": "Verifica installazione",
        "intro": (
            "Controlla localmente i file del pacchetto Provelume installato. La verifica non "
            "usa la rete e non legge la conoscenza della Instance né configurazioni personali."
        ),
        "status.package_integrity_verified": "Integrità del pacchetto verificata",
        "status.modified_installation": "Installazione modificata",
        "status.verification_unavailable": "Verifica non disponibile",
        "reason.package_integrity_verified": (
            "Tutti i file del pacchetto con hash corrispondono al RECORD del wheel."
        ),
        "reason.modified_installation": (
            "I file del pacchetto installato differiscono dal RECORD del wheel."
        ),
        "reason.verification_unavailable": (
            "I metadati o il legame con il pacchetto importato non consentono una "
            "verifica completa dell'integrità."
        ),
        "label.package": "Pacchetto",
        "label.version": "Versione",
        "label.checked": "File controllati",
        "label.tracked": "File tracciati",
        "label.unhashed": "Record senza hash",
        "label.unexpected": "File inattesi",
        "label.network": "Rete utilizzata",
        "label.origin": "Origine ufficiale",
        "network.none": "No",
        "origin.not_established": "Non stabilita dai soli metadati locali",
        "findings.title": "Problemi rilevati",
        "findings.none": "Non sono stati rilevati problemi di integrità nei file del pacchetto.",
        "findings.unavailable": (
            "Non è disponibile un elenco completo dei problemi perché la verifica non è "
            "stata completata."
        ),
        "findings.truncated": (
            "Altri problemi sono stati omessi al raggiungimento del limite di sicurezza."
        ),
        "issue.missing_file": "File mancante",
        "issue.modified_file": "File modificato",
        "issue.unreadable_file": "File non leggibile",
        "issue.unreadable_path": "Percorso del pacchetto non leggibile",
        "issue.unexpected_file": "File inatteso nel pacchetto",
        "issue.unsafe_path": "Percorso non sicuro o collegamento simbolico",
        "issue.unhashed_record": "Voce RECORD senza hash",
        "issue.unsupported_hash": "Hash non supportato",
        "issue.invalid_record": "Voce RECORD non valida",
        "issue.scan_limit": "Limite di sicurezza raggiunto",
        "detail.missing_file": "Manca un file dichiarato nel RECORD del wheel.",
        "detail.modified_file": "Il file installato differisce dal RECORD del wheel.",
        "detail.unreadable_file": (
            "Non è stato possibile leggere completamente il file installato."
        ),
        "detail.unreadable_path": (
            "Non è stato possibile scansionare completamente il percorso del pacchetto."
        ),
        "detail.unexpected_file": (
            "È presente un file del pacchetto non dichiarato nel RECORD del wheel."
        ),
        "detail.unsafe_path": (
            "Il percorso non è sicuro o contiene un collegamento simbolico o un reparse "
            "point del filesystem."
        ),
        "detail.unhashed_record": (
            "Il RECORD del wheel non fornisce un hash crittografico per questo file."
        ),
        "detail.unsupported_hash": "L'algoritmo hash del RECORD non è supportato.",
        "detail.invalid_record": "L'hash del RECORD è malformato o non canonico.",
        "detail.scan_limit": (
            "La verifica ha raggiunto il proprio limite di sicurezza operativa."
        ),
        "explain.integrity": (
            "La corrispondenza con il RECORD del wheel indica che i file installati non "
            "sono cambiati rispetto alla distribuzione installata."
        ),
        "explain.origin": (
            "Un wheel coerente può comunque non essere ufficiale. Per verificare l'origine "
            "servono un manifest, una firma o un'attestazione considerati affidabili."
        ),
        "back.home": "Home",
    },
}


def installation_translator(language: str) -> Callable[[str], str]:
    catalog = MESSAGES.get(language, MESSAGES["en"])
    fallback = MESSAGES["en"]

    def translate(key: str) -> str:
        return catalog.get(key, fallback.get(key, key))

    return translate

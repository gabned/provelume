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
            "no network and never reads Instance knowledge or personal configuration. "
            "A local operator can configure release evidence when the server starts to "
            "compare installed Core bytes with a verified wheel."
        ),
        "bundle_config.title": "Release evidence",
        "bundle_config.configured": (
            "A local operator configured release evidence when this server process started. "
            "This page displays that cached verification result."
        ),
        "bundle_config.not_configured": (
            "No release bundle was configured when this server process started. This page "
            "displays the cached RECORD-only result."
        ),
        "bundle_config.note": (
            "Browser and API clients cannot choose or change server-local paths. Restart "
            "the server with trusted operator options, or use the local verification CLI."
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
        "label.origin": "Origin evidence",
        "label.release_linkage": "Release-wheel linkage",
        "label.bundle_version": "Bundle version",
        "label.bundle_tag": "Bundle tag",
        "label.bundle_commit": "Source commit",
        "label.manifest_sha256": "Manifest SHA-256",
        "label.wheel": "Release wheel",
        "label.wheel_files": "Wheel package files",
        "label.linkage_checked": "Installed files compared",
        "network.none": "No",
        "origin.not_established": "Not established by local package metadata",
        "origin.trusted_manifest_sha256_matched": (
            "Matched operator-supplied manifest SHA-256"
        ),
        "linkage.status.verified": "Installed bytes match the release wheel",
        "linkage.status.installed_bytes_differ": (
            "Installed bytes differ from the release wheel"
        ),
        "linkage.status.verification_unavailable": "Release linkage unavailable",
        "linkage.status.bundle_invalid": "Release bundle invalid",
        "linkage.status.wheel_invalid": "Release wheel invalid",
        "linkage.reason.verified": (
            "The bundle is internally consistent, its candidate wheel and internal RECORD "
            "are valid, and installed Core files match the wheel bytes."
        ),
        "linkage.reason.installed_bytes_differ": (
            "At least one installed Core file is missing, changed or absent from the "
            "verified release wheel."
        ),
        "linkage.reason.verification_unavailable": (
            "The requested comparison could not be completed safely."
        ),
        "linkage.reason.bundle_invalid": (
            "The supplied directory did not satisfy the bounded release-bundle contract."
        ),
        "linkage.reason.wheel_invalid": (
            "The candidate wheel could not be validated completely and safely."
        ),
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
        "issue.release_file_missing": "Release-wheel file missing",
        "issue.release_file_modified": "Release-wheel file differs",
        "issue.release_unexpected_file": "File absent from release wheel",
        "issue.bundle_invalid": "Invalid release bundle",
        "issue.wheel_invalid": "Invalid release wheel",
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
        "detail.release_file_missing": (
            "A Core file declared by the release wheel is not installed."
        ),
        "detail.release_file_modified": (
            "The installed Core file differs from the release wheel bytes."
        ),
        "detail.release_unexpected_file": (
            "The installed Core file is not present in the release wheel."
        ),
        "detail.bundle_invalid": (
            "The local release bundle is malformed, inconsistent or outside a safety limit."
        ),
        "detail.wheel_invalid": (
            "The candidate release wheel or its internal RECORD is invalid."
        ),
        "explain.integrity": (
            "A matching wheel RECORD shows that installed package bytes have not changed "
            "since this distribution was installed."
        ),
        "explain.origin": (
            "A self-consistent bundle can still have an unauthenticated publisher. A "
            "matching operator-supplied manifest SHA-256 proves only that the checked "
            "bundle matches the bytes identified by the independently obtained hash."
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
            "usa la rete e non legge la conoscenza della Instance né configurazioni personali. "
            "Un operatore locale può configurare l'evidenza di release all'avvio del server "
            "per confrontare i file Core installati con un wheel verificato."
        ),
        "bundle_config.title": "Evidenza di release",
        "bundle_config.configured": (
            "Un operatore locale ha configurato l'evidenza di release all'avvio di questo "
            "processo server. Questa pagina mostra il risultato della verifica memorizzato."
        ),
        "bundle_config.not_configured": (
            "All'avvio di questo processo server non è stato configurato alcun bundle di "
            "release. Questa pagina mostra il risultato RECORD-only memorizzato."
        ),
        "bundle_config.note": (
            "I client browser e API non possono scegliere o modificare percorsi locali del "
            "server. Riavvia il server con opzioni operatore affidabili oppure usa la CLI "
            "di verifica locale."
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
        "label.origin": "Evidenza sull'origine",
        "label.release_linkage": "Collegamento al wheel di release",
        "label.bundle_version": "Versione del bundle",
        "label.bundle_tag": "Tag del bundle",
        "label.bundle_commit": "Commit sorgente",
        "label.manifest_sha256": "SHA-256 del manifest",
        "label.wheel": "Wheel di release",
        "label.wheel_files": "File del pacchetto nel wheel",
        "label.linkage_checked": "File installati confrontati",
        "network.none": "No",
        "origin.not_established": "Non stabilita dai soli metadati locali",
        "origin.trusted_manifest_sha256_matched": (
            "Corrisponde allo SHA-256 del manifest fornito dall'operatore"
        ),
        "linkage.status.verified": "I file installati corrispondono al wheel di release",
        "linkage.status.installed_bytes_differ": (
            "I file installati differiscono dal wheel di release"
        ),
        "linkage.status.verification_unavailable": (
            "Collegamento alla release non disponibile"
        ),
        "linkage.status.bundle_invalid": "Bundle di release non valido",
        "linkage.status.wheel_invalid": "Wheel di release non valido",
        "linkage.reason.verified": (
            "Il bundle è internamente coerente, il wheel candidato e il suo RECORD sono "
            "validi e i file Core installati corrispondono ai byte del wheel."
        ),
        "linkage.reason.installed_bytes_differ": (
            "Almeno un file Core installato manca, è cambiato o non è presente nel wheel "
            "di release verificato."
        ),
        "linkage.reason.verification_unavailable": (
            "Non è stato possibile completare il confronto in sicurezza."
        ),
        "linkage.reason.bundle_invalid": (
            "La directory fornita non soddisfa il contratto limitato del bundle di release."
        ),
        "linkage.reason.wheel_invalid": (
            "Non è stato possibile validare completamente e in sicurezza il wheel candidato."
        ),
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
        "issue.release_file_missing": "File del wheel di release mancante",
        "issue.release_file_modified": "File diverso dal wheel di release",
        "issue.release_unexpected_file": "File assente dal wheel di release",
        "issue.bundle_invalid": "Bundle di release non valido",
        "issue.wheel_invalid": "Wheel di release non valido",
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
        "detail.release_file_missing": (
            "Un file Core dichiarato dal wheel di release non è installato."
        ),
        "detail.release_file_modified": (
            "Il file Core installato differisce dai byte del wheel di release."
        ),
        "detail.release_unexpected_file": (
            "Il file Core installato non è presente nel wheel di release."
        ),
        "detail.bundle_invalid": (
            "Il bundle locale è malformato, incoerente o supera un limite di sicurezza."
        ),
        "detail.wheel_invalid": (
            "Il wheel candidato o il suo RECORD interno non è valido."
        ),
        "explain.integrity": (
            "La corrispondenza con il RECORD del wheel indica che i file installati non "
            "sono cambiati rispetto alla distribuzione installata."
        ),
        "explain.origin": (
            "Un bundle coerente può comunque avere un publisher non autenticato. La "
            "corrispondenza con uno SHA-256 fornito dall'operatore dimostra soltanto che il "
            "bundle controllato coincide con i byte identificati dall'hash ottenuto separatamente."
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

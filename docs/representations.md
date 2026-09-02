# Representations and support — user guide

The Representations page explains two different things:

1. what Provelume is able to do with a content profile on this computer;
2. which new universal derived bundles are present and valid in this Instance.

Opening the page, calling the API or running the inspection commands is read-only and offline.
It does not scan a provider, start OCR, create a preview, repair a bundle or update a component.

## Read the six levels separately

- **Preserve** means exact bytes can be retained with their checksum.
- **Inspect** means bounded structural facts can be read.
- **Extract** means a derived representation such as text can be produced.
- **Preview** means an inert local view is available.
- **Local enrich** needs the stated local component and configuration.
- **AI enrich** is unavailable in S01; there is no AI path.

An available Preserve row does not promise any other level and does not make the content
searchable. `declared_state` says what the public profile permits. `effective_state` says what is
available now. `reason` and `missing_component` explain a degraded or unavailable level using a
closed value rather than a guess.

## Inspect locally

```bash
provelume representation-support INSTANCE
provelume representation-support INSTANCE --profile-id lectio-local-ocr-v1
provelume representations INSTANCE
provelume representation INSTANCE REPRESENTATION_ID
```

The same data is available at `/representations`, `/api/v1/representations/support`,
`/api/v1/representations` and `/api/v1/representations/{representation_id}` on the local
loopback-only service.

## Originals and compatibility

Universal representations are removable derived state. Removing or rebuilding one does not edit
the Original, canonical knowledge or provider data. A new recipe creates a new representation and
keeps the older identity in history.

Lectio document extraction, local OCR, email, Google read-only, SRT/WebVTT and cross-source finding
records appear as compatibility views. Their stored bytes are not converted. Existing schema-2
Instances do not need a migration, and no Markdown file is created beside an Original.

Backup, restore and portable transfer include this durable derived state and verify it deeply.
Corrupt, missing or mismatched output is rejected; it is never promoted into canonical knowledge.

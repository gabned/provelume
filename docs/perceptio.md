# Perceptio integrated pilot

Perceptio is the read-only, local-first integration surface for the exact photo, audio, video and
CSV/XLSX/ZIP representation profiles already admitted by the `0.10.0` plan. During S07 it remains
an unpublished candidate: seeing the page or API does not make `0.10.0` available. The package,
embedded runtime and Windows product identity stay `0.9.0` until the separate release boundary.

## One evidence journey

Open **Perceptio pilot** in the Browser or run:

```bash
provelume perceptio-status INSTANCE
provelume perceptio-status INSTANCE --version-id VERSION_ID --limit 100
provelume perceptio-representation INSTANCE REPRESENTATION_ID
```

The service, CLI, `GET /api/v1/perceptio` and `/perceptio` Browser page consume one projection.
Each result keeps the exact Version and representation identity beside:

- the gallery, player/waveform/transcript/subtitle or table/archive family surface;
- effective availability and the profile’s closed support evidence;
- component, adapter and version evidence;
- warnings as uncertainty rather than verified facts;
- reversible correction annotations and exact page/time/region/sheet/cell/member anchors;
- derived outputs and a link back to the family-specific view.

The detail and anchor routes are also GET-only. No integrated endpoint queues work, applies a
correction, removes an output or changes a Source.

## States and accessibility

The contract names happy, empty, loading, degraded, unavailable, interrupted and recovery states.
Unavailable optional codecs, models or tools stay visible; they never trigger discovery, download
or remote fallback. The server-rendered EN/IT view uses landmarks, headings, native tables,
definition lists, links and disclosure controls. It inherits the product focus indicator, skip
link, reflow, forced-colour and reduced-motion behavior. Meaning is never carried only by colour.

## Privacy, hostile content and limits

Reads perform no network request and never write to the Original, canonical records, provider
data or source files. GPS coordinates remain excluded from default export. Profile text is rendered
as escaped text: HTML, formulas, scripts, prompt-like strings, archive members and embedded media
are never executed by this surface. Existing per-profile byte, count, duration, pixel, expansion,
process, memory, disk and deadline limits remain authoritative and fail closed.

## Recovery and release boundary

Representation remove/rebuild, Instance backup/restore and portable transfer retain their existing
contracts. Release qualification also exercises clean install, upgrade from published `0.9.0`,
rollback and uninstall data preservation through the permanent release and Windows workflows.
Perceptio becomes available only after the separate exact-version PR, reviewed `main` commit,
offline release verification, immutable `v0.10.0` tag and canonical asset publication all agree.

See the [S07 qualification map](qualification/perceptio-s07.md),
[support plan](releases/0.10.0.md), [privacy contract](privacy-network.md) and
[Italian guide](perceptio.it.md).

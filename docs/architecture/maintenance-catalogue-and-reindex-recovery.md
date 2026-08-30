# Maintenance catalogue and reindex recovery

`0.8/S03` supplies the bounded maintenance vertical slice published in the `v0.8.0` Vigilia
preview. Its first usable operation is a durable full or incremental SQLite FTS generation; other
already-safe local operations use the same S01 scheduler and journal.

## Closed catalogue

The catalogue is code-defined and returned in one stable order. Unknown action IDs fail closed.

| Action | Current availability | Authority and recovery |
| --- | --- | --- |
| `search.reindex.full` | available | rebuildable derived write; resumable |
| `search.reindex.incremental` | available | rebuildable derived write; resumable |
| `maintenance.library_rebuild` | available | rebuildable derived write; restart-only |
| `maintenance.source_reconcile` | available | read-only exact Source scope; resumable |
| `maintenance.validate` | available | read-only; restart-only |
| `maintenance.resource_snapshot` | available | content-free Instance observation; restart-only and idempotent |
| `maintenance.original_assurance` | available | read-only verification; restart-only |
| `maintenance.duplicate_scan` | available | review-only derived evidence; restart-only |
| `maintenance.backup_create` | unavailable | explicit destination required |
| `maintenance.backup_verify` | unavailable | explicit destination required |

Every entry declares scope, authority, mutability, scheduling, dry-run and recovery capabilities.
Every catalogue read also declares that the read itself uses no network, canonical mutation or
automatic deletion. A Source-reconciliation terminal receipt separately records whether the
operator-selected Source is a mounted-network class. An unavailable entry cannot create a policy
or job. In particular, the scheduler never invents a backup destination and never turns
validation, assurance or a duplicate scan into repair.

Resource observations use the same journal but persist their own immutable, job-bound sample before
the terminal receipt. Their categories, capacity semantics, threshold settings and replay boundary
are defined in [resource statistics, capacity and thresholds](resource-statistics-capacity-and-thresholds.md).

Available actions use exact Instance scope and the existing manual/interval/calendar policy
contract, including explicit timezone, DST policy, quiet window, deterministic jitter, missed-run
policy and bounded retry. Run now remains an explicit operator action. There is no daemon, startup
task, hidden timer, provider call or cloud fallback.

## Dry-run plan and temporary-space gate

A reindex dry run reads canonical metadata and existing derived-index evidence without writing a
maintenance record or candidate. It reports:

- requested mode and actual `full` or `incremental` strategy;
- exact current Document-to-Version identities and the sorted selected Document IDs;
- canonical and searchable-knowledge fingerprints;
- selected item count and Original-byte estimate;
- bounded candidate-space requirement and free bytes observed at the Instance index filesystem.

Incremental strategy is used only when the active database exactly matches its own valid metadata,
even if that metadata is now out of date relative to current Versions. A missing, invalid or
content-mismatched baseline falls back visibly to a full strategy. Execution repeats the
temporary-space check and fails with the closed `insufficient_temporary_space` code before creating
a run or changing the active index.

The estimate is a safety preflight, not a capacity forecast. S05 implements durable local Instance
capacity thresholds and trends through the separate content-free resource-snapshot action.

## Durable run and isolated candidate

Scheduler jobs remain under `state/scheduler/`. S03 adds strict content-free records:

```text
state/maintenance/reindex-runs/reindex_<job-uuid>.json
indexes/reindex-candidates/reindex_<job-uuid>-r<revision>-<generation>.sqlite3
indexes/reindex-candidates/reindex_<job-uuid>-r<revision>-<generation>.json
```

The durable run binds the job, plan revision/digest, generation ID, exact current and incremental
baseline Version maps, selected IDs, estimate, candidate-relative references, cursor, counts, base
scheduler progress and closed phase. It stores no text, path, URL, credential, query or caller
idempotency value. Candidate files are derived and rebuildable.

A full generation starts from an empty FTS table. An incremental generation uses SQLite's backup
primitive to copy the verified active database, then deletes and reinserts only selected Document
rows. Removed or trashed Documents are deleted from the candidate only; no canonical record or
Original is deleted. A missing readable derived representation is an explicit skipped item.

## Checkpoint and activation order

For each selected item the worker performs this bounded sequence:

1. delete the candidate row for that Document and insert the exact planned current Version when a
   readable derived representation exists;
2. commit SQLite and fsync the candidate;
3. commit a monotonic scheduler `executing` checkpoint with absolute progress;
4. atomically advance the maintenance cursor and counts.

Deleting before insertion makes an item replay idempotent. Before resuming, the worker reconstructs
the exact expected candidate from the bound baseline plus the committed prefix and compares every
row, so a partial SQLite copy or mismatched processed/unprocessed row starts a new plan revision. A
crash after the SQLite commit but before the scheduler checkpoint repeats the item safely. A crash
after the scheduler checkpoint but before the maintenance cursor leaves the candidate exactly one
row ahead; recovery advances the cursor to the already-advertised item without processing or
counting it twice. Progress never moves backward.

After the final item, the worker compares every candidate row with exact current canonical and
derived evidence. It writes the same generation-bound metadata into the candidate database and its
JSON sidecar, then records `activating`. One atomic filesystem replacement makes the already
validated database active: readers therefore see either the previous complete database or the new
complete database, never a partly built candidate. A second atomic replacement updates the JSON
sidecar. If the process stops between those replacements, replay reads the metadata embedded in the
new database, verifies every row, restores the sidecar and completes the same generation. Readers
also prefer valid generation metadata embedded in the active database during this window, so they
do not mistake the intentionally stale sidecar for a reason to rebuild. A later ordinary
incremental refresh removes the embedded generation marker in the same SQLite transaction that
changes rows before writing its new sidecar.

If the process stops after activation but before the scheduler receipt, replay recognizes the exact
active generation ID, job ID, plan digest and content, completes the durable run and writes one
terminal receipt without rebuilding or duplicating rows. If canonical state changes before an
unfinished candidate resumes, the same job starts a new plan revision and candidate while retaining
monotonic cumulative journal progress. Missing candidate files after restore/import likewise cause
a safe restart; they are never treated as canonical loss.

## Persistence, validation and surfaces

Maintenance run records are part of durable `state/`, so verified backup/restore and portable
export/import preserve them without an Instance schema migration. `indexes/` remains declared
`rebuild`, so candidates and the active FTS database are excluded when derived state is rebuilt.
Deep validation rejects unsafe references, unknown fields, identity/digest mismatches, cursor/count
disagreement, invalid clocks and any claim of network use, canonical mutation or automatic
deletion.

Local surfaces are:

```bash
provelume maintenance-catalog INSTANCE
provelume maintenance-action INSTANCE search.reindex.full
provelume maintenance-plan INSTANCE search.reindex.incremental
provelume maintenance-policy-create INSTANCE search.reindex.full \
  --state enabled --mode calendar --timezone Europe/Rome --calendar-time 03:30
provelume maintenance-run INSTANCE search.reindex.incremental \
  --idempotency-key operator-request-1
provelume maintenance-runs INSTANCE
provelume maintenance-reindex-run INSTANCE REINDEX_RUN_ID
```

The `/api/v1/maintenance` family is read-only. The EN/IT `/maintenance` Browser has semantic parity;
only a loopback request with the per-process CSRF token can queue Run now. API and remote Browser
reads expose no Instance or Source path. S04 reconciliation cursors and runs are specified in
[Source reconciliation cursors and lifecycle](source-reconciliation-cursors-and-lifecycle.md).

## Deliberate limits

- S05 resource policies, durable file/byte/category/trend statistics and capacity thresholds are
  implemented by the content-free Instance snapshot contract; they do not enforce quotas.
- Backup scheduling remains unavailable until an explicit destination/verification parameter can
  be bound without weakening path privacy or cleanup authority.
- No maintenance schedule performs repair, purge, retention deletion, destination cleanup,
  provider writes, network discovery or release publication.

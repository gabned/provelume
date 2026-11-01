# Concordia S06 — explicit Inbox transit and guarded input exit

Status: **PREPARATION CANDIDATE / NOT_ACCEPTED**. The authorized S06 work is
stacked on S05 #432 at `c3ceda00e41888abd1a8fba3b9935151e3a2b283`.
S01–S04 #431 and S05 retain their original owners, BIND objects and outcomes.
The missing original #431 BIND still prevents formal integration of that chain.
This candidate does not replace it. Package identity remains 0.14.0/development;
Lifecycle v2 remains deferred. S07 setup/UI and later slices have separate scope.

## Product behavior and authority

An Inbox is an explicitly selected **local Folder Source** with an independently
confirmed Inbox policy. Its default policy preview chooses **transit**; **keep**
is always available. Ordinary and existing Sources without that decision remain
keep-file. Neither a display name containing “Inbox”, component installation nor
global OCR configuration converts a Source or grants deletion authority.

Conversion uses the existing local review authority and atomic/CAS transaction.
It previews the exact current input inventory, pins the physical root and binds
the Source/configuration revision. An unresolved owned ingestion run blocks
conversion. The same Source identity, observer, scheduler policy, Documents,
Versions, history, provenance and independent consents remain in place. The
existing lifecycle lock pauses admission during confirmation; there is no second
watcher or queue. A concurrent refresh must finish/reconcile before conversion.

Existing inputs, including unpreserved files present at confirmation, are excluded
from future automatic exit by their exact retained input identities. A second
review selects existing preserved acquisitions and their exact index producer/job.
Converting to transit never consumes the old backlog. Converting to keep stops
future exits and does not recreate copies already consumed.

New acquisitions after consent retain an immutable admission binding policy,
Source, acquisition, input identity/hash/size and OCR settings/requirement. Failed
admission cannot undo preservation and grants no exit. Only an actual successful
producer receipt triggers an exit attempt under the existing scheduler owner.
Cancelled, failed, skipped, paused, partial or missing work is insufficient. A
required OCR stage stays required even if its policy is later disabled; an
explicit limited-result decision still needs its exact completed OCR/index proof.

## Completion, R8 and recovery

`preserved`, `flow_complete` and `input_exited` are distinct. The existing S05
resolver verifies the current Version, exact Original bytes, selected text,
Source policy, terminal producer receipt/attempt and actual FTS contribution.
S06 adds evidence for the processing part of the existing `source.refresh` job:
freeze exact run/acquisitions and selected contributions before active indexing,
then publish its attempt proof before scheduler success. Source-scoped refresh
does not gain missing-text recovery or full-rebuild permission from this policy.
OCR, reviewed processing and maintenance keep their own existing producer adapters.

Application index writers now participate in the **existing Instance lifecycle
lock**, joining only the current process/thread's actual held ownership. Another
thread/process cannot use the diagnostic lock JSON as authority. No new global
lock is introduced. Policy/configuration mutations retain their existing local
ownership boundaries. Final Windows disposition also pins the selected config,
canonical identity, Original, index and selected proof/text files against external
write/replacement, and rechecks the resolver and consent before the effect.

Exit opens the exact input with read/delete access and no sharing, refuses reparse
entries, multiple hard links, changed metadata or changed bytes, and retains
parents/root through `SetFileInformationByHandle(FileDispositionInfo)` and close.
No path-based unlink fallback follows an error. Unsupported filesystems, permissions,
existing incompatible readers/writers or platforms retain the input visibly.
POSIX exit is explicitly unqualified: advisory locking plus unlink cannot provide
this conditional deletion contract against arbitrary concurrent writers.

Only the removed input's empty ancestor directories below the configured root are
eligible for cleanup. Each is separately opened with delete access, compared with
its observed physical identity and dispositioned by the kernel, which refuses
nonempty directories. Root and unrelated empty directories remain. Unsupported
cleanup leaves the directory intact.

Before disposition, an immutable intent links the exact reviewed permit or
future-work consent, input/selection proof and existing operation ID. Confirmed
exit has a separate immutable result. Repeated completed release is a no-op.
Before-exit interruption retains the copy and can retry after fresh revalidation.
If disposition may have happened but its outcome was not durably recorded, absence
is **outcome_unknown**, never reconstructed success. Changed/replaced/new input is
retained for a fresh preview. Reads never repair state. A later index failure
requires index recovery and never recreates an Inbox input.

Deep validation and coherent backup preserve policies, review chains, admissions,
intents and results. Historical records are checked against their exact consent
and operation; their applicability is not inherited by restored/replaced physical
roots or rebuilt indexes. Native power-loss durability beyond the exercised OS
primitives is not claimed.

Bounds are explicit: 128 Inbox policies, 1,000 scanned entries and 25 MiB total
input per preview, 100 exact inputs per reviewed release, 10,000 retained
admissions/actions and the existing review byte/history limits. Overflow blocks;
no unbounded traversal, silent truncation, automatic splitting or cap increase.

## Local operator path / percorso operatore locale

Register a local folder with the existing `folder-source-register` command first.
Use the same Source ID throughout. The CLI exposes separate preview and confirmation:

```bash
provelume inbox-transit-preview INSTANCE SOURCE_ID grant > grant.json
provelume inbox-transit-confirm INSTANCE SOURCE_ID grant.json --request-id inbox-grant-1
provelume inbox-transit-preview INSTANCE SOURCE_ID policy > policy.json
provelume inbox-transit-confirm INSTANCE SOURCE_ID policy.json --request-id inbox-policy-1
provelume inbox-transit-status INSTANCE SOURCE_ID
```

The policy preview defaults to transit and lists existing files before use.
Choose `policy --mode keep` to retain inputs. `grant --disable` previews revocation.
The existing browser capability page also supports the scoped grant in all seven
catalogues; the full Inbox/setup interface belongs to S07. Machine diagnostics
remain local operator output, not new product UI copy.

For existing preserved inputs, `items.json` is an exact list of objects containing
`acquisition_id`, `producer` (`processing` or `maintenance`) and `job_id`. Select a
known exact successful producer, rather than searching for a favorable proof:

```bash
provelume inbox-transit-preview INSTANCE SOURCE_ID release --items items.json > release.json
provelume inbox-transit-confirm INSTANCE SOURCE_ID release.json --request-id inbox-backlog-1
provelume inbox-transit-release INSTANCE REVIEW_RECEIPT_ID
```

**Italiano.** L'anteprima di una nuova Inbox propone il transito; `--mode keep`
mantiene i file d'ingresso. Le cartelle esistenti conservano il comportamento
precedente finché non confermi una conversione specifica. I file già presenti
restano esclusi dall'uscita automatica: selezionali in una seconda anteprima, dopo
la conservazione dell'Originale e la prova d'indicizzazione della Versione esatta.
Installare l'OCR non autorizza una Source. OCR in attesa/errore o prova mancante
trattengono l'ingresso; AI, classificazione, organizzazione ed esportazione restano
facoltativi e indipendenti. Tornare a conserva-file interrompe le uscite future,
senza ricreare le copie già consumate. Un esito incerto rimane esplicito e non si
deduce il completamento dalla sola assenza del file. Originals e documenti restano
consultabili quando la copia d'ingresso esce. I comandi operano solo sulla Source
selezionata e richiedono una conferma dopo l'anteprima.

## Qualification

Synthetic tests cover new/existing/keep policies, exact current producer evidence,
future-only admission, separate backlog confirmation, required OCR, read-only
previews/status, changed input/Original/FTS/policy/inventory, grant revocation,
duplicate refresh, interruption/unknown outcome, hard links, FIFO, limits,
coherent backup/restore and lifecycle contention. Native Windows tests additionally
exercise exclusive input sharing, parent rename refusal, handle disposition,
idempotent release and bounded empty-directory cleanup. Hostile file contents
are never executed. No new dependency, network endpoint or license is introduced.

Ruff/full pytest/diff/pin, current permanent Linux/Windows CI and native Windows
results are recorded against the exact candidate in its owner PR. Earlier S05
evidence remains bound to S05. Exact production-PC installation, browser/desktop,
accessibility and linguistic observations remain **ASSIGNED_TO_MAINTAINER / NOT_RUN**
on the sole user's Windows 11 Pro 25H2 PC. No VM, Home edition, separate account
or additional tester is introduced as a prerequisite. No personal input was used.

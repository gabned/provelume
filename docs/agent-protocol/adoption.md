# Canonical dependency and local authority

Agent Protocol is maintained in `gabned/agent-protocol`. The repository's own
product source is a distinct boundary. The dependency under
`tools/agent_protocol_core/` is an exact vendored distribution, including modes,
notices, original licenses and historical validators. Change native adapters
outside that directory; never patch the vendor into a local fork.

The accepted consumer pin binds operational and Work revisions, authenticated
release location, archive digest, complete source inventory and document manifest.
The provenance record retains predecessor registration and the original-to-vendor
mapping. Verify every byte and mode before importing. Candidate-supplied manifests,
recalculated digests or PR bodies cannot authenticate adoption.

A future upgrade starts under the currently accepted local change-control and
native gates. Qualify the complete candidate and all introduced commits, native
entrypoints, collection, event guards, tests, exact-head reviews and actual triggers.
Use normal expected-head merge and observe required post-merge checks. Keep any
still-used legacy route valid during the transition; do not weaken PRODUCT policy.

For the operational status of this adoption, use its local PR ledger and original
verification receipts. An inventory or cross-repository campaign matrix is only a
derived view. Installing these documents is not proof of successful adoption,
migration, cleanup or laboratory verification.

## Predecessor qualification of bounded compatibility maintenance

The independent Core bootstrap contract requires a separately predecessor-qualified
transfer for frozen legacy changes. Initial transfer-v1/v2 remains unchanged; it
cannot describe a successor of an already integrated Core base. The maintenance-v1
route below supplies that missing qualification for one direct successor, at most
16 existing legacy code/test files, exact before/after blobs, modes and final tree.
It cannot change guards, workflows, policy, notices, registries or dependency files.
It permits neither new/deleted files nor candidate merge commits or intermediate
history. A changed base, head, PR, file or mode requires a new predecessor record
and its ordinary qualification; the current record cannot be reused for another fix.

The record in this document is a proposal until its Provelume owner passes the
accepted native, exact-head CI, review, scope/effect and normal merge gates and the
host independently verifies actual main and post-merge CI. Only then may an
authenticated operator select that accepted predecessor commit and run its verifier
outside the destination candidate checkout. Read the record from Git at that exact
accepted commit, never from a PR body, working tree, arbitrary JSON or a recomputed
digest. Authenticate repository IDs and the current Core PR/base/head separately.

Run `python tools/agent_protocol_transfer.py verify-maintenance --source-root
PREDECESSOR_CHECKOUT --destination CORE_CHECKOUT --accepted-predecessor ACCEPTED_SHA
--repository gabned/agent-protocol --repository-id 1393711644 --pr CORE_PR
--expected-base CORE_BASE --expected-head CORE_HEAD`. This offline command verifies
complete unreplaced Git history and the exact retained bytes; its BYTES_VERIFIED
receipt is not merge or publication permission.

For the exact recorded maintenance only, that accepted predecessor qualification
satisfies the destination bootstrap's GATE_CHANGE_REQUIRES_PREDECESSOR_QUALIFICATION
prerequisite. Retain the original frozen-scope refusal as a refusal, not PASS. The
host must verify that its sole reason is the unchanged guard's frozen-legacy check,
and reobserve complete successful destination Linux/Windows conformance, every run
attempt/job, reviews/threads, base/head/tree and unchanged guard/workflow bytes.
Any other failure blocks integration. Use only the ordinary expected-head merge
API; a server denial stops the operation, with no protection changes or alternate
write mechanism. Verify actual ordered parents/tree and all post-merge checks.
This transfer route grants no general frozen-file exception, release/publication,
consumer adoption or PRODUCT authority. Preserve original receipts and validators
at their immutable revisions. Consumer pin adoption is a separate qualified PR.

The proposed transfer below qualifies Core PR #4's existing two-file timeout fix.
Its conformance is recorded in that owner's ledger; the Provelume qualification
owner must independently observe it before accepting this predecessor record.

```agent-protocol-maintenance
{
  "schema": "agent-protocol-maintenance/v1",
  "predecessor": "gabned/provelume",
  "repository": "gabned/agent-protocol",
  "repository_id": 1393711644,
  "pr": 4,
  "base": "7287e2c3c6dd42d1aad1c7eac3c68043f8a0cf69",
  "head": "33132bd431738d9d30ebd384f47794275d36bc68",
  "tree": "701d7eb95984b87f8ecfd667b77d8f9386b3265b",
  "files": [
    {
      "path": "compat/legacy/tests/test_agent_protocol_work_check.py",
      "mode": "100644",
      "before_blob": "29b83ff18422a9a60bc862de2a2e29924fb12bfe",
      "after_blob": "4b545e3328284303c5de2651b0ab636f42b53f77",
      "sha256": "dfd433f8a2b3607a171a072a71dc307adabda2ca32357e58c283dedace0d6f20"
    },
    {
      "path": "compat/legacy/tools/agent_protocol_work_check.py",
      "mode": "100644",
      "before_blob": "eb0487ba00e938c17df536526c58ceb644683137",
      "after_blob": "53f7f1ef669d7c4a451a36be540ff1e8197f8714",
      "sha256": "192dc9f81c2f567240146cd738227d455554f8fdbea5e5b7b4a46f28b0ee5a6e"
    }
  ]
}
```

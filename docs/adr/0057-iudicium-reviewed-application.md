# ADR 0057 — Reviewed classification policy, application and undo

Status: S03 implementation candidate, #361, parent #349; not qualification.
Base accepted S02 is `b3dbb03fd0eb0b9efa40a8a7d2151e8149fe89b5`.

Use the existing domain review coordinator, retained authority/receipts, lifecycle
lock, preimage checks and registered atomic Instance transaction. Initial policy
creation, updates and human-directed placement require fresh explicit review.
The policy has a closed Source/path/target/profile/language scope, UTC expiry,
bounded application budget and classification-metadata-only impact. Targets bind
current canonical record bytes; labels never supply authority. Every changed
scope is reviewed. A newly qualified quality scope also requires policy review;
old pending automatic requests cannot become authority after qualification.

An AI assessment supplies evidence for a separate manual domain decision, never
write permission. That decision explicitly selects current destinations, retains
the assessment/receipt association and uses existing independently configured
local review authority. The immutable assessment retains its original unevaluated
quality, null confidence and absence of mutation/automation authority. A caller,
model response or synthetic confidence cannot qualify automatic application.
S03 has no real classifier quality evidence; automatic application fails closed
pending the distinct real, scoped qualification in S05. No inference, activation,
consent renewal, extra worker or parallel queue is introduced by review.

Undo checks the exact committed application, current classification preimage and
source/Version identity. It restores the prior placement, including unclassified,
without overwriting a foreign later placement. It remains an explicit remedial
decision after policy expiry/revocation, AI Off or disposal of the private body.
No Original/Version bytes or historical provenance edges are removed; accounting
and original execution/review receipts remain. Repeating a request is idempotent;
an already consumed assessment is never an automatic replay opportunity.

The existing atomic writer gains a conditional classification-only removal. It
atomically moves that exact preimage into its private stage and retains a durable
copy before any publication. Prepared recovery restores only its own removal;
foreign replacements fail closed. Committed cleanup verifies the intended absence.
Only registered review transactions may remove a classification path. Existing
write-only product transactions retain their schema-1 bytes; the removal uses an
explicit product transaction schema-2 operation. This is unrelated to deferred
Agent Protocol Lifecycle v2 and supplies no new Protocol or deployment authority.

Required qualification includes atomic interruption/recovery/foreign-write cases,
initial and changed review scope, expiry/budget/current source-policy-profile
denials, explicit manual placement and conflict-safe undo, unqualified automation
refusal, both interfaces/catalogs and existing local-only nonce/Instance controls.
Full unchanged native, every exact-source workflow/attempt/job/review, binding,
fresh preflight, normal expected-head merge and actual-main gates remain required.
Human/catalog observations remain NOT_RUN/UNVERIFIED and label review NOT_REVIEWED,
nonblocking by the maintainer's #349 comment6186153379; no observations are invented.

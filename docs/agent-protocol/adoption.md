# Canonical dependency and local authority

Agent Protocol is maintained in `gabned/agent-protocol`. The repository's own
product source is a distinct boundary. The dependency under
`tools/agent_protocol_core/` is an exact vendored distribution, including modes,
notices, original licenses and historical validators. Change native adapters
outside that directory; never patch the vendor into a local fork.

The accepted consumer pin binds operational and Work revisions, an explicitly
selected authenticated release or canonical Git origin, archive digest, complete
source inventory and document manifest. Git origin acceptance is independent of
the candidate and verified by the shared Core; a self-consistent digest is not
source authentication. Existing release pins and historical proofs stay valid.
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

## Predecessor qualification of the pytest security update

CVE-2025-71176 / GHSA-6w46-j5rx-g56g affects pytest before9.0.3. The
Provelume maintainer supplied the visible Dependabot1 text identifying the vendored
requirements-test.txt/pytest8.4.2 and explicitly requested remediation before the
single Entitas publication. This is a test/development dependency; it is absent
from the qualified product runtime SBOM. That runtime observation does not repair
the vulnerable test requirement. Existing bot proposals and all published releases
remain preserved. Protected API accessibility or alert closure is not inferred.

The independent bootstrap requires predecessor qualification for frozen dependency
changes. Historical maintenance-v1 remains unchanged and cannot admit them. The
separate `verify-dependency-update` operation qualifies only this exact seven-file
single-child update: requirements-test.txt must change from the exact pytest8.4.2 /
ruff0.16.9 payload to pytest9.0.3 / unchangedruff0.16.9. The other six closed existing
paths may contain only mechanical1.5.1-to-1.5.2 distribution identity replacements.
No guard, workflow, registry, notices, legacy bytes, other dependencies, executable
behavior or modes can change. A self-consistent altered manifest cannot expand
that scope. One direct successor, complete unreplaced Git histories, exact blobs,
modes, full tree and complete delta remain mandatory. This is not a general frozen
surface exception; old records, validators and refusal results retain their meaning.

The following exact record remains a proposal until this predecessor PR passes its
accepted native/CI/review/binding/fresh preflight/normal-merge and actual-main gates.
Only afterward may the authenticated host select the independently accepted
predecessor commit, read this record from immutable Git and run that revision's
verifier outside the destination candidate checkout:

```bash
python tools/agent_protocol_transfer.py verify-dependency-update \
  --source-root PREDECESSOR_CHECKOUT --destination CORE_CHECKOUT \
  --accepted-predecessor ACCEPTED_SHA --repository gabned/agent-protocol \
  --repository-id 1393711644 --pr 6 \
  --expected-base 1a11fe76712ee65ca2160d2ae3789330946a57f2 \
  --expected-head 552c8fdb8e37ed7d38f41f5defbd7f3daa2747f4
```

Retain the original destination frozen-scope refusal as a refusal. The host must
prove its sole reason is the unchanged guard's frozen dependency check, then
independently reobserve all successful destination Linux/Windows conformance,
every applicable run/attempt/job, all reviews/threads and actual base/head/tree.
Every other failure blocks. Use only a normal expected-head merge; a platform
denial stops integration without protection edits, force/admin bypass or an
alternative write. Observe ordered actual parents/tree and all post-merge checks.
The verifier grants neither merge nor publication authority. Necessary immutable
Protocol1.5.2 publication must separately satisfy its accepted publication contract;
consumer pin adoption and the final Provelume0.14 publication remain separately
qualified operations under the existing campaign/owners. No later product release
or additional consumer rollout is started.

```agent-protocol-pytest-security
{
  "schema": "agent-protocol-pytest-security/v1",
  "predecessor": "gabned/provelume",
  "repository": "gabned/agent-protocol",
  "repository_id": 1393711644,
  "pr": 6,
  "base": "1a11fe76712ee65ca2160d2ae3789330946a57f2",
  "head": "552c8fdb8e37ed7d38f41f5defbd7f3daa2747f4",
  "tree": "86867a21ab46ae5e058b8db1f4e5d39c61afc405",
  "files": [
    {
      "path": "pyproject.toml",
      "mode": "100644",
      "before_blob": "7692cdddf12796b35dc3453a26514a0c3f2c643d",
      "after_blob": "e022fa997daff815256e203f1c44aeeb42c5ef58",
      "sha256": "1222fba6a890990a93505659df4975d8059a890953e20c1ca4b31060f365f861"
    },
    {
      "path": "requirements-test.txt",
      "mode": "100644",
      "before_blob": "ee3cb431a52d036ab6c458f70b28e945b435e041",
      "after_blob": "e22ab8b46e5f22c757b9b67c22fb44c88a06aa27",
      "sha256": "3e38bebc4236cff3a31cb709371d342f38d5aea67013d2f8ab37e6b319eb9333"
    },
    {
      "path": "src/agent_protocol/__init__.py",
      "mode": "100644",
      "before_blob": "bf38edb3d885c0ff12e67204e9d19bf9b0f5b129",
      "after_blob": "6ffa40e680efedaa0fbc9f52e720a3cd4b8281b0",
      "sha256": "8da561e0a1381434e9b249da54a616d0bde8ea3239950e90d3051f7ead17b8a7"
    },
    {
      "path": "src/agent_protocol/source.py",
      "mode": "100644",
      "before_blob": "81b754df2115201be2ce04233bc63150f94c35cd",
      "after_blob": "2289a8ecc6b36c213c23d34da7875a5e73aeb574",
      "sha256": "5e082db4d1ddf24574bdc4bf16162ea7cb1b87340a14545a13b4fcc9334eb8b2"
    },
    {
      "path": "tests/test_packaging.py",
      "mode": "100644",
      "before_blob": "f2ae98901def69ef6e2f8d53a92b3f67967ba7e0",
      "after_blob": "974f87274950160fac22e96bc5e46c92b167aa88",
      "sha256": "497e2304bf867342b597a64fa1b77976f7454a2117c7a53bc9ea5e8c372419aa"
    },
    {
      "path": "tests/test_source.py",
      "mode": "100644",
      "before_blob": "10e032618108aff4931be93df5e6eda6fa7debbb",
      "after_blob": "c3aae8d427e9c19355481d460e24082142815f74",
      "sha256": "411425ce92eda0f4d7b8b84e3afadba14b986860079d9e45d06a97ecbc44c050"
    },
    {
      "path": "tools/package.py",
      "mode": "100644",
      "before_blob": "3c24e1947d29704acd4095689dea521e4531a1e3",
      "after_blob": "9d99bb6d985997db09f784c1e11bf4a837ca6dd2",
      "sha256": "4dbbfeb7b17ed08c442aa0bc351d83578b1d3b52b76e48badbabb63cba304848"
    }
  ]
}
```

## Proposed predecessor transfer for the trusted PR metadata reader

The original PR408 attempt1/run39505179474/job118912204986 failed with curl22 /
HTTP403 before event-guard. Its log has neither response headers nor response body
and does not establish rate limit, access restrictions or any other specific cause.
Preserve that failure and every previous adoption attempt; do not rerun or relabel it.

This separate predecessor proposal changes no workflow, host profile, canonical
vendor or historical validator. It is usable only after its own complete native,
exact-head CI, review, scope/effect, fresh preflight, normal merge and actual-main
qualification under the independently accepted base. A candidate cannot select
this proposal or its own verifier as authority. Lifecycle v2 stays deferred and
existing owners and PR-local ledgers remain authoritative.

The existing qualifier's frozen-path refusal remains unchanged. Once independently
accepted, this narrowly qualified transfer supplies only the prerequisite for the
exact workflow payload recorded below. It is not a general frozen-file exception,
waiver, profile edit, missing-CI override or merge authority. Historical maintenance,
pytest dependency transfers and all original refusals keep their own scope.

An authorized host reads the record and invokes that accepted revision's verifier
outside the workflow candidate checkout:

```bash
python tools/agent_protocol_transfer.py verify-trusted-pr-reader \
  --source-root ACCEPTED_PREDECESSOR_CHECKOUT --destination WORKFLOW_CHECKOUT \
  --accepted-predecessor ACCEPTED_MAIN --expected-base ACCEPTED_MAIN \
  --expected-head WORKFLOW_HEAD --repository gabned/provelume \
  --repository-id 1343746770 --pr WORKFLOW_PR
```

The host independently authenticates those live GitHub coordinates and the
accepted predecessor. The operation verifies complete unreplaced Git history,
one direct successor of that exact predecessor, only the existing ci.yml file,
100644 mode and exact before/after blobs and SHA256. Any changed base or head
requires fresh observation and verification. Any other payload, intermediate
history, merge commit, rename or additional file is refused. This same-repository
successor contract avoids a circular record containing its own future merge SHA;
the independently accepted predecessor is the exact required candidate parent.

The host retains the ordinary frozen-path refusal and must prove it is the sole
scope refusal. All other required source, CI/run/attempt/job/original-byte,
review/thread, native, effect/binding and fresh normal expected-head merge gates
remain mandatory. No caller may remove frozen paths from the accepted profile,
relabel the ordinary qualifier's result or ignore another failure. The transfer
receipt is BYTES_VERIFIED only. Actual main ordered parents/tree and every required
post-merge check must be observed before acceptance. Platform denial stops the
operation without protection changes, force/admin bypass or alternative writes.

The exact payload grants pull-requests:read only to the trusted-base job, keeps
public Git acquisition credential-free, and confines github.token to a separate
metadata-acquisition step. No candidate tree is checked out or executed there.
The subsequent base guard receives data without the token in its environment;
it still validates current PR/event/base/head and the complete Git delta, refusing
missing or inconsistent input. The reader refuses redirects and logs only selected
non-secret HTTP diagnostic headers, with no automatic retry. Its purpose is to
make the required read authenticated and future failures diagnosable; it does not
claim a proven historical cause or a future PASS.

```agent-protocol-trusted-pr-reader
{
  "schema": "agent-protocol-trusted-pr-reader/v1",
  "repository": "gabned/provelume",
  "repository_id": 1343746770,
  "path": ".github/workflows/ci.yml",
  "mode": "100644",
  "before_blob": "0431ad5b99ea95a743c4f179316e6eef711a567f",
  "after_blob": "9d33d2b5b6df4eec045df1fb9f6e758a96e5c4b5",
  "after_sha256": "e172ac571097ed871f96fc68d407fb5195319f2f97f679c69717b6671dd910f4"
}
```

The exact reviewed workflow delta is retained here so the payload can be inspected
before any frozen file is modified:

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -120,7 +120,8 @@
   agent-change-control:
     name: Agent change control (trusted base)
     if: github.event_name == 'pull_request_target'
-    permissions: {}
+    permissions:
+      pull-requests: read
     runs-on: ubuntu-latest
     timeout-minutes: 5
     env:
@@ -134,6 +135,27 @@
         uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6.2.0
         with:
           python-version: "3.12"
+
+      - name: Acquire current PR metadata with read-only authentication
+        shell: bash
+        env:
+          GH_TOKEN: ${{ github.token }}
+        run: |
+          set -euo pipefail
+          test "$REPOSITORY" = 'gabned/provelume'
+          test "$GITHUB_API_URL" = 'https://api.github.com'
+          mkdir -p .agent
+          status=0
+          curl --fail-with-body --silent --show-error --max-redirs 0 \
+            --header "Authorization: Bearer $GH_TOKEN" \
+            --header 'Accept: application/vnd.github+json' \
+            --header 'X-GitHub-Api-Version: 2022-11-28' \
+            --dump-header .agent/current-pr.headers \
+            --output .agent/current-pr.json \
+            "${GITHUB_API_URL}/repos/${REPOSITORY}/pulls/${PR_NUMBER}" || status=$?
+          awk 'tolower($0) ~ /^(http\/|date:|x-github-request-id:|x-ratelimit-(limit|remaining|reset|used|resource):|retry-after:)/ {print}' \
+            .agent/current-pr.headers
+          test "$status" -eq 0

       - name: Evaluate the untrusted head with the trusted base guard
         shell: bash
@@ -150,9 +172,6 @@
           test "$observed_head" = "$HEAD_SHA"
           mkdir -p .agent
           git diff --name-status -M -z "$BASE_SHA" "$HEAD_SHA" > .agent/name-status.z
-          curl --fail --silent --show-error --location \
-            "${GITHUB_API_URL}/repos/${REPOSITORY}/pulls/${PR_NUMBER}" \
-            > .agent/current-pr.json
           python tools/agent_protocol_v2.py event-guard \
             --event "$GITHUB_EVENT_PATH" \
             --current-pr .agent/current-pr.json \
```

After actual acceptance of this correction, refresh adoption against the accepted
base using a supported linear successor and preserve PR406/408 and their original
owner and failures. Requalify source and actual-main adoption before resuming the
existing PRODUCT final owner. This proposal authorizes no SDK draft mutation,
application publication, new release, deployment or lifecycle activation.

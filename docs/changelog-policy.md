# Changelog and planned-version policy

`CHANGELOG.md` records completed public history and the current `Unreleased` work. Versioned roadmap and release-plan labels are planning coordinates, not immutable reservations.

## Published history is immutable

- Never renumber an existing tag, published release, dated changelog heading, released package version or embedded release identity.
- Never rewrite an already published changelog item merely to make a later plan look sequential.
- `Unreleased` content may move into a release only during the reviewed release-preparation change that sets the package and embedded identity.

## Unplanned release insertion

When a new, independently releasable activity must be inserted before one or more already numbered but unreleased roadmap releases, the inserted activity takes the version slot at the insertion point. Every later unreleased planned release moves forward to the next valid slot in the repository's existing version lane.

The shift is one atomic planning change:

1. identify the insertion point and the applicable semantic-version lane;
2. assign the inserted activity the displaced unreleased version;
3. move every later unreleased planned version forward by one slot, preserving relative order;
4. update every canonical planning surface in the same pull request, including roadmap, release plan, issue registry and any future-version table;
5. preserve stable issue identifiers, scope, dependencies, acceptance criteria and ownership links;
6. leave the current package version, tags, published releases and dated changelog headings unchanged until their own release preparation;
7. fail closed instead of guessing when the lane, insertion point or complete set of planning surfaces is ambiguous.

Patch or follow-up releases that belong to a parent release move with that parent. They do not become independent insertion slots unless the roadmap explicitly promotes them to standalone release scope.

## Closed contract

The repository-wide planning contract is:

```text
UNPLANNED_RELEASE_INSERTION_POLICY: SHIFT_FORWARD
SHIFT_SCOPE: ALL_LATER_UNRELEASED_PLANNED_RELEASES
PUBLISHED_HISTORY: IMMUTABLE
CURRENT_VERSION_UPDATE: RELEASE_PREPARATION_ONLY
FOLLOWUP_RELEASES: MOVE_WITH_PARENT
ATOMIC_PLANNING_SURFACES: REQUIRED
PRESERVE_RELATIVE_ORDER: TRUE
PRESERVE_SCOPE_AND_ISSUE_IDENTITY: TRUE
CONFLICT_STATE: ROADMAP_VERSION_SHIFT_CONFLICT
```

`ROADMAP_VERSION_SHIFT_CONFLICT` means the change stops without partial renumbering. A valid shift must not leave duplicate future versions, reuse a published version, create an unexplained gap inside the shifted sequence or update only a subset of the canonical planning documents.

## Changelog entries

- Add notable work under `Unreleased` while it is under development.
- Use concise, externally verifiable language and avoid absolute security or privacy guarantees.
- Move `Unreleased` entries into a dated release heading only when package identity, embedded identity, tag intent and release documentation are coherent.
- Documentation-only governance changes do not change the package version, but may be recorded under `Unreleased` when they materially alter the public release contract.

## Development slices and installable checkpoints

A forecast release such as `0.5.0` may be delivered through multiple bounded development slices
without pretending that every agent turn is a package release. Slice identifiers are planning and
ownership coordinates, never versions, tags or published changelog headings:

- `0.5/S01`, `0.5/S02`, ... identify homogeneous delivery slices;
- `0.5/S01/F01`, `0.5/S01/F02`, ... identify fine-tuning passes belonging to one slice;
- `0.5/S01/F01-a`, `0.5/S01/F01-b`, ... identify micro-adjustments that need a reviewable work
  identity but not an independent release.

Each release has one canonical parent issue and at most one open owner slice pull request. A slice
has a closed scope and complete tests; its ownership closes before the next slice opens. A slice,
fine-tuning pass or micro-adjustment does not change package/embedded identity and does not create
a tag unless a separate release-preparation change authorizes an installable checkpoint.

When an intermediate installer provides real user-testing value, use standards-compliant
pre-release identities: package `0.5.0a1`, `0.5.0b1` or `0.5.0rc1` paired respectively with tags
`v0.5.0-alpha.1`, `v0.5.0-beta.1` or `v0.5.0-rc.1`. After final `0.5.0` publication, a released
correction uses `0.5.1`, `0.5.2`, and so on under the existing patch policy. Collapsed identifiers
such as `0.51` or `0.511`, and letter-suffixed package versions, are not used because package,
updater and semantic-version ordering must remain unambiguous.

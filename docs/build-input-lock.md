# Python build-input lock

`requirements-build.txt` contains the reviewed direct tools used to create
Provelume's Python wheel and source distribution. `requirements-build.lock`
freezes the complete resolved toolchain for the currently certified release
target:

- Linux x86-64;
- CPython 3.12.14;
- wheel artifacts only.

Every locked project has an exact version and one or more SHA-256 artifact
hashes. The lock header also records the digest of the direct requirements file.

## Validate the committed lock

Validation does not contact a package index:

```bash
python scripts/build_input_lock.py check \
  --lock requirements-build.lock \
  --direct requirements-build.txt \
  --json
```

The command fails if the direct requirements changed, a project is duplicated,
a hash is missing or malformed, or a direct pin is absent or resolves to another
version.

## Materialize the locked wheelhouse

The certified builder resolves only wheel artifacts and requires every artifact
to match the committed lock:

```bash
python -m pip download \
  --require-hashes \
  --only-binary=:all: \
  --dest .build-wheelhouse \
  --requirement requirements-build.lock
```

After this step, the two isolated distribution builds install from the local
wheelhouse with package-index access disabled.

## Deliberately regenerate the lock

Regeneration is a reviewed maintenance operation, not an automatic update during
a release:

```bash
rm -rf .build-wheelhouse-next
python -m pip download \
  --only-binary=:all: \
  --dest .build-wheelhouse-next \
  --requirement requirements-build.txt
python scripts/build_input_lock.py generate \
  --wheelhouse .build-wheelhouse-next \
  --direct requirements-build.txt \
  --target-python "CPython 3.12.14" \
  --target-platform "Linux x86_64" \
  --output requirements-build.lock
```

A lock update should be reviewed like a source change. Reviewers should inspect:

- direct requirement changes;
- added, removed or upgraded transitive projects;
- artifact hashes and wheel-only status;
- upstream release/security notes where relevant;
- deterministic-build and full repository CI results.

## Scope and limits

The lock freezes Python distribution build tooling, not runtime dependencies,
SBOM tooling, the GitHub-hosted runner image or future Windows packaging tools.
It supports the current deterministic component claim but is not by itself proof
of an independently reproducible release.

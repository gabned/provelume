# Reviewed Ubuntu CPython 3.12 build-input lock

Provelume maintains a target-specific lock for the current official Python package builder:

- system: Linux/Ubuntu;
- machine: x86_64;
- implementation: CPython;
- Python: 3.12.14.

The lock is deliberately narrower than a universal dependency lock. Future Windows installers, containers and additional Python/platform targets require their own policies and evidence.

## Files

`build-lock/ubuntu-py312-x86_64.lock.json` is the machine-readable audit record. It includes the direct requirements hash, target identity, exact wheel filenames/sizes/SHA-256 values, dependency metadata and a content-derived lock ID.

`build-lock/ubuntu-py312-x86_64.requirements.txt` is the corresponding pip input. Every line is an exact version and one reviewed target-wheel hash.

Both files must describe the same wheel set. `scripts/build_input_lock.py verify` reconstructs the expected requirements lock from the JSON and downloaded bytes; manually changing one file cannot produce a green gate. Schema identifiers are validated as integers rather than truthy values, so malformed boolean schema versions fail closed.

## CI verification

The `Reviewed build-input lock` workflow:

1. downloads the exact lock with `--require-hashes --no-deps`;
2. recomputes and verifies every wheel identity and direct requirements hash;
3. creates a fresh virtual environment;
4. installs all locked wheels with `PIP_NO_INDEX=1` and `--no-deps`;
5. runs the double-build deterministic package comparator from that offline environment.

A missing wheel, index substitution, hash mismatch, lock drift or nondeterministic package output fails the workflow.

## Refresh procedure

A lock refresh is reviewed like source code.

1. Create a repository branch whose name begins with `lock/`.
2. Change `requirements-build.txt` when the direct toolchain changes, or manually dispatch `Refresh reviewed build-input lock` against that branch.
3. The branch-only workflow resolves binary wheels for the declared target, generates both lock files, redownloads them through the pip hash gate and verifies the JSON policy.
4. The workflow commits changed lock files to the same `lock/` branch.
5. Add a normal human-authored review commit when needed so repository checks evaluate the final bot-generated lock pair.
6. Open or update a pull request and review the complete dependency/version/wheel/hash delta.
7. Merge only after ordinary read-only CI, deterministic builds and independent/offline rebuild gates are green.

The refresh workflow intentionally does not write to `main`. Its job guard accepts only `refs/heads/lock/**`. A lock-only generated commit does not recursively trigger another refresh.

## Review checklist

Reviewers should check:

- direct tool changes are intentional and documented;
- transitive additions/removals follow from the direct dependency metadata;
- no source distribution or unexpected non-wheel input entered the lock;
- package names and versions are plausible for the declared target;
- wheel filenames match the target or are platform-independent;
- license/notice implications are addressed when the closure changes;
- CI redownloaded and verified every committed hash;
- offline deterministic package and independent rebuild evidence remains green.

## Current assurance boundary

The lock makes the transitive build-wheel identities durable and reviewable in the public repository. It still depends on the availability of those artifacts at the public index unless a retained mirror is added. The base Ubuntu runner, Python distribution and pip bootstrap are declared by workflow rather than included in this lock.

The accurate claim is **reviewed target build-input lock plus offline deterministic package evidence**. It is not yet a complete platform-independent reproducible-release guarantee.

# Provelume build-input locks

This directory contains reviewed, target-specific identities for Python package build inputs. These files belong to release infrastructure only; they are not Provelume Core runtime dependencies.

## Current target

The first lock covers the official Python package builder declared by repository workflows:

- Ubuntu/Linux;
- x86_64;
- CPython 3.12.14.

Files:

- `ubuntu-py312-x86_64.lock.json` — complete machine-readable wheel identities, dependency metadata, target, requirements hash and content-derived lock ID;
- `ubuntu-py312-x86_64.requirements.txt` — exact pip pins and one reviewed SHA-256 for each target wheel.

The two files are generated and verified together by `scripts/build_input_lock.py`. CI redownloads exactly these wheel hashes, verifies the JSON policy, installs with package-index access disabled and runs the deterministic package build gate.

Do not edit individual versions or hashes manually. Follow `docs/release/build-input-lock.md` and use a reviewed `lock/**` branch refresh.

A target lock is not a universal lock. Additional Python versions, operating systems, machine architectures, Windows installers or container builders require separate files and evidence.

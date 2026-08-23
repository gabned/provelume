# GitHub repository policy

Target policy for the public repository:

- `main` is the canonical branch;
- normal changes arrive through pull requests;
- required CI checks must pass before merge;
- force-pushes and direct history rewrites on `main` are prohibited;
- squash merge is preferred for focused public history;
- secrets and private-reference material are rejected by CI and review;
- release tags are created only from reviewed `main` commits;
- ordinary CI never publishes an official release;
- the separate `.github/workflows/release.yml` workflow rejects tags whose version differs from package metadata or whose commit is not already present on `main`;
- official Core/self-hosted artifacts are built only from this public repository;
- public releases carry license/third-party notices, SHA-256 checksums, a machine-readable SBOM, provider-independent manifest and build-provenance attestations.

Repository-level branch protection should be configured in GitHub to enforce these rules. `.github/workflows/ci.yml` provides the public merge checks; release publication remains a distinct tag-triggered boundary.

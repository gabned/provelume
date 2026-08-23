# GitHub repository policy

Target policy for the public repository:

- `main` is the canonical branch;
- normal changes arrive through pull requests;
- required CI checks must pass before merge;
- force-pushes and direct history rewrites on `main` are prohibited;
- squash merge is preferred for focused public history;
- secrets and private-reference material are rejected by CI and review;
- release tags are created only from reviewed `main` commits;
- public releases must carry license and third-party notice information.

Repository-level branch protection should be configured in GitHub to enforce these rules. The workflow in `.github/workflows/ci.yml` provides the initial required check.

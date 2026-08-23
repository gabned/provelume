# Clean-room development boundary

The public Provelume repository starts from a fresh Git history and public product requirements. The private Nexus repository remains a reference instance and private knowledge archive.

## Allowed inputs

Publicly stated product requirements, sanitized interface descriptions, newly written tests, public standards/documentation, and deliberate reimplementation work are valid inputs to the public repository.

## Prohibited transfers

Do not transfer Nexus personal data, generated indexes, email content, credentials, deployment state, private product research, private roadmaps, private architectural notes, private Git commits/branches/tags, or source files merely by copying them from the private repository.

## Extraction rule

When existing private behavior should become product behavior, first describe the required capability as a public contract. Implement and test that contract in the public repository without relying on private paths, identifiers, fixtures or hidden state.

## Review rule

Every extraction PR should be understandable and testable from the public repository alone. If a reviewer needs access to Nexus to understand why the code works, the boundary has not been completed yet.

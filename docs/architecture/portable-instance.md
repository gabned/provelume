# Portable Instance format (schema 1)

A Provelume Instance is an ordinary directory. The first schema uses:

```text
<instance>/
  provelume.yml
  originals/
    sha256/
  knowledge/
    sources/
    acquisitions/
    originals/
    documents/
    versions/
    provenance/
  state/
    derived/
  indexes/
```

`provelume.yml` contains instance identity, local UI/network defaults and operator source bindings. Source paths are written relative to the Instance directory when the platform permits it; absolute paths are allowed only when a relative representation is impossible or the operator explicitly configures one. Canonical objects never require a Git remote.

`originals/` and `knowledge/` are durable. `state/derived/` and `indexes/` are rebuildable. Secrets must not be stored in versionable configuration.

Path locators use `/` as the logical separator even on Windows. Absolute locators and `..` traversal are rejected before they are used as Instance-relative references.

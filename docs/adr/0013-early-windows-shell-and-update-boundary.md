# ADR 0013: Early Windows product shell with an unsigned update boundary

- Status: Accepted
- Date: 2026-08-27

## Context

The Core already exposes useful local capabilities, but trying them on Windows requires Python,
command-line setup and manual server startup. Product development benefits from exercising the
installation, version, About and update lifecycle before the deeper roadmap is complete.

The existing release chain verifies Python distributions. It does not yet establish deterministic
Windows installer output, Authenticode identity, detached provider-independent signing or safe
automatic rollback. Bringing a usable shell forward must not overstate those guarantees or make
GitHub a required Core runtime dependency.

## Decision

`0.4.0` adds a per-user x64 Windows preview installer built from the already assured candidate
wheel plus a retained hash-locked Windows runtime/tool input set. PyInstaller freezes a launcher
and runtime; Inno Setup creates the per-user package. The portable Instance remains outside the
installed runtime and is preserved on upgrade and uninstall.

About identity is always local. Update checks are disabled by default, manual or explicitly
enabled at startup, and disclose their network boundary. The domain contract is
`provelume-windows-update.json`; GitHub Releases is only the first catalogue/download transport.
The launcher validates bounded metadata and verifies installer size and SHA-256 before offering a
user-confirmed handoff to the normal installer.

The manifest records `automatic_apply: false`, `publisher_authentication: not_established` and
`platform_signature: unsigned_preview`. The UI and documentation preserve those exact limits.

## Consequences

- a Windows user can install and open Provelume without Git or a separately installed Python;
- the application/update/Instance boundaries are exercised before the knowledge feature set is
  mature;
- ordinary local use remains useful with update checks disabled and without GitHub;
- the official release bundle can checksum and attest the traceable Windows artifact without
  calling it reproducible or signed;
- Windows may show SmartScreen for this preview;
- unattended apply, independent publisher authentication, Authenticode, runtime slots, backup,
  rollback and interrupted-update recovery remain required before the later safe-updater claim.

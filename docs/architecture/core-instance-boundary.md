# Core / Instance architecture boundary

## Core

Provelume Core owns reusable ingestion, provenance, normalization, extraction, indexing contracts, source identity and other domain behavior that can run independently of any one person's archive or deployment.

Core exposes stable interfaces to Instances and managed services. It does not know about private Nexus paths, provelume.com billing/tenant logic or a specific hosting provider.

## Instance

A Provelume Instance assembles Core for one self-hosted deployment. It owns operator configuration, storage locations, connector credentials, deployment manifests and instance-local lifecycle concerns.

Instance configuration is external state. Public examples belong in Git; real values do not.

## Managed cloud

The managed service at provelume.com is a separate consumer of versioned Core artifacts. Its web application, tenancy, billing, cloud orchestration, hosted-service policy and provider-specific infrastructure live in the private `gabned/provelume.com` repository.

The cloud repository must not vendor the Core source tree. Core should be consumed through explicit versioned releases, packages or container images so public and managed deployments share the same product engine without duplicating ownership.

## Dependency direction

`provelume.com cloud -> released Provelume Core`

`self-hosted Instance -> released/local Provelume Core`

`Provelume Core -> neither Nexus nor provelume.com`

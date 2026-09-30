/** Compatibility entrypoint for demonstrated Work callers.
 * Current lifecycle and historical collection share one canonical distribution.
 * Remove this shim only after the legacy caller/test inventory is empty and
 * original receipts remain recoverable at their immutable source revisions.
 * Host verifies the accepted pin before loading connector entrypoints.
 */
export {collectSource, connectorFailure, connectorPayload, createWorkConnector,
  collectWorkSession, collectPreflight, createEvidenceCollector}
  from './agent_protocol_core/compat/legacy/tools/agent_protocol_work_collect.mjs';
export {collectLifecycle} from './agent_protocol_core/tools/collect.mjs';

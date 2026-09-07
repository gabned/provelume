/** Read-only Work collector. Dependencies are supplied by the authorized host.
 * fetchJson(url): decoded JSON from the real GitHub connector GET tool.
 * fetchFile(args): optional typed connector file tool; immutable ref + base64.
 * saveBlob(sha, response): stores base64 bytes for mandatory offline verification.
 * hasBlob(sha): optional verified content-addressed cache; never skips final hashing.
 * This module has no token, HTTP client, publication or process API.
 */
export async function collectSource({repository, fetchJson, saveBlob,
  fetchFile = null, hasBlob = async () => false,
  now = () => new Date().toISOString(), maxCalls = 2000,
  persistObservation = null, progress = null}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (!Number.isInteger(maxCalls) || maxCalls < 1 || maxCalls > 10000) throw Error("invalid connector call budget");
  if (typeof fetchJson !== "function" || typeof saveBlob !== "function") throw Error("connector host capabilities required");
  if (fetchFile !== null && typeof fetchFile !== "function") throw Error("invalid file connector capability");
  if (persistObservation !== null && typeof persistObservation !== "function") throw Error("invalid persistence capability");
  if (progress !== null && typeof progress !== "function") throw Error("invalid progress capability");
  const prefix = `https://api.github.com/repos/${repository}`;
  let calls = 0;
  const observations = [];
  async function get(suffix) {
    if (++calls > maxCalls) throw Error("bounded connector call budget exhausted");
    const url = prefix + suffix;
    let response;
    try { response = await fetchJson(url); }
    catch (error) {
      if (persistObservation) await persistObservation({url, observed_at:now(), status:"UNKNOWN", response:null});
      throw error;
    }
    const observation = {url, observed_at: now(), response};
    if (persistObservation) await persistObservation(observation);
    if (!response || typeof response !== "object" || response.error || Number(response.status) >= 400) {
      throw Error("connector observation unavailable; no inferred success");
    }
    observations.push(observation);
    return observation;
  }
  const metadata = await get("");
  if (metadata.response.full_name !== repository || !metadata.response.default_branch) throw Error("repository identity mismatch");
  const branch = metadata.response.default_branch;
  const ref = `/git/ref/heads/${encodeURIComponent(branch)}`;
  const before = await get(ref);
  const commit = before.response.object?.sha;
  if (!/^[0-9a-f]{40}$/.test(commit || "") || before.response.object.type !== "commit" ||
      before.response.ref !== "refs/heads/" + branch) throw Error("invalid commit identity");
  const commitObservation = await get(`/git/commits/${commit}`);
  const treeSha = commitObservation.response.tree?.sha;
  if (commitObservation.response.sha !== commit || !/^[0-9a-f]{40}$/.test(treeSha || "")) throw Error("commit/tree identity mismatch");
  let tree = (await get(`/git/trees/${treeSha}?recursive=1`)).response;
  if (tree.truncated === true) {
    const queue = [{sha: treeSha, path: "", ancestors: []}];
    const entries = [];
    for (let index = 0; index < queue.length; index++) {
      const node = queue[index];
      if (node.ancestors.includes(node.sha)) throw Error("recursive tree cycle");
      const part = (await get(`/git/trees/${node.sha}`)).response;
      if (part.sha !== node.sha || part.truncated !== false || !Array.isArray(part.tree)) throw Error("incomplete subtree");
      for (const entry of part.tree) {
        if (typeof entry.path !== "string" || entry.path.includes("/") || ["", ".", ".."].includes(entry.path)) throw Error("invalid subtree path");
        const path = node.path ? node.path + "/" + entry.path : entry.path;
        entries.push({...entry, path});
        if (entries.length > 100000) throw Error("tree entry budget exceeded");
        if (entry.type === "tree") queue.push({sha: entry.sha, path, ancestors: [...node.ancestors, node.sha]});
      }
    }
    tree = {sha: treeSha, truncated: false, tree: entries};
  }
  if (tree.sha !== treeSha || tree.truncated !== false || !Array.isArray(tree.tree)) throw Error("incomplete tree");
  if (tree.tree.length > 100000) throw Error("tree entry budget exceeded");
  const blobs = new Map();
  let total = 0;
  for (const entry of tree.tree) {
    if (typeof entry.path !== "string" || entry.path.includes("\\") || entry.path.includes("\0") ||
        entry.path.split("/").some(part => ["", ".", ".."].includes(part))) throw Error("invalid source path");
    if (!((entry.type === "blob" && ["100644", "100755"].includes(entry.mode)) ||
          (entry.type === "tree" && entry.mode === "040000"))) throw Error("symlink/submodule adapter unavailable");
    if (!/^[0-9a-f]{40}$/.test(entry.sha || "")) throw Error("invalid tree object identity");
    if (entry.type === "blob") {
      if (!Number.isInteger(entry.size) || entry.size < 0 || entry.size > 100 * 1024 * 1024) throw Error("blob size limit");
      total += entry.size;
      if (total > 512 * 1024 * 1024) throw Error("source size limit");
      blobs.set(entry.sha, entry);
    }
  }
  let downloaded = 0, cached = 0;
  for (const [sha, entry] of blobs) {
    if (await hasBlob(sha)) { cached++; continue; }
    let blob;
    if (fetchFile) {
      if (++calls > maxCalls) throw Error("bounded connector call budget exhausted");
      const args = {repository_full_name: repository, path: entry.path, ref: commit, encoding: "base64"};
      let response;
      try { response = await fetchFile(args); }
      catch (error) {
        if (persistObservation) await persistObservation({tool:"github_fetch_file", arguments:args,
          observed_at:now(), status:"UNKNOWN", response:null});
        throw error;
      }
      const observation = {tool: "github_fetch_file", arguments: args, observed_at: now(), response};
      if (persistObservation) await persistObservation(observation);
      observations.push(observation);
      blob = connectorPayload(response);
    } else {
      blob = (await get(`/git/blobs/${sha}`)).response;
    }
    // A decoded-text tool result is not the raw GitHub blob API. Never guess an
    // encoding or manufacture original bytes from it. Typed file reads preserve
    // their actual envelope above; this size comes independently from the tree.
    blob = checkedBase64(blob, entry);
    await saveBlob(sha, blob);
    downloaded++;
    if (progress) await progress({phase:"SOURCE", calls, downloaded_blobs:downloaded,
      cached_blobs:cached, total_blobs:blobs.size, push_qualified:false});
  }
  const after = await get(ref);
  if (after.response.object?.sha !== commit || after.response.object?.type !== "commit") throw Error("default moved during acquisition");
  return {
    snapshot: {schema: "agent-work-source/v1", repository, commit_sha: commit, tree_sha: treeSha, tree},
    anchor: {default_branch: branch, repository: metadata, before, commit: commitObservation, after},
    acquisition: {calls, downloaded_blobs: downloaded, cached_blobs: cached,
      observations, authentication: "AUTHORIZED_HOST_RESPONSIBILITY", push_qualified: false},
  };
}

/** Unwrap only supported tool envelopes; error content is never source data. */
export function connectorPayload(result) {
  let value = result;
  for (let depth = 0; depth < 4; depth++) {
    if (!value || typeof value !== "object" || value.isError === true || value.error ||
        Number(value.status) >= 400) throw Error("connector tool failed; no fallback or inferred success");
    if (value.structuredContent) { value = value.structuredContent; continue; }
    if (value.result && typeof value.result === "object") { value = value.result; continue; }
    return value;
  }
  throw Error("unsupported connector envelope");
}

function checkedBase64(blob, entry) {
  if (blob.sha !== entry.sha || blob.encoding !== "base64" || typeof blob.content !== "string") {
    throw Error(`lossless blob unavailable: ${entry.path}; use github_fetch_file with encoding=base64 and the exact commit ref`);
  }
  // GitHub inserts CR/LF into base64; other whitespace and malformed padding fail.
  const encoded = blob.content.replace(/[\r\n]/g, "");
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw Error(`invalid base64: ${entry.path}`);
  }
  const size = encoded.length / 4 * 3 - (encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0);
  if (size !== entry.size || (blob.size !== undefined && blob.size !== entry.size)) {
    throw Error(`lossless blob size mismatch: ${entry.path}; empty/truncated content cannot be repaired`);
  }
  // Final Git blob/subtree/root rehashing by agent_protocol_work_source.py remains
  // mandatory, including for cache hits. This normalization grants no authority.
  return {sha: entry.sha, encoding: "base64", size: entry.size, content: blob.content};
}

/** Bind the advertised Work tools once. No tokens, HTTP fallback or tool discovery. */
export function createWorkConnector({fetch, fetchFile}) {
  if (typeof fetch !== "function" || typeof fetchFile !== "function") {
    throw Error("Work requires github_fetch and github_fetch_file capabilities");
  }
  return {
    fetchJson: async url => {
      const value = connectorPayload(await fetch({url}));
      if (typeof value.content !== "string") throw Error("connector JSON content unavailable");
      const decoded = JSON.parse(value.content);
      if (!decoded || typeof decoded !== "object") throw Error("connector returned non-JSON resource");
      return decoded;
    },
    fetchFile,
  };
}

/** One observational startup/resume call, followed by the native local preflight.
 * Saved blobs survive interruption; hasBlob must verify bytes on every reuse.
 * Never reuses policy/CI observations or local check success from a former call.
 */
export async function collectWorkSession(options) {
  const source = await collectSource(options);
  const observations = await collectPreflight(options);
  if (observations.default_branch.status !== "OBSERVED" ||
      observations.default_branch.response?.name !== source.anchor.default_branch ||
      observations.default_branch.response?.commit?.sha !== source.snapshot.commit_sha) {
    throw Error("default moved or unavailable before local preflight");
  }
  return {...source, observations, local_preflight: "NOT_RUN", push_qualified: false};
}

/** Bounded observational preflight. Unknown policy/Actions remain UNKNOWN.
 * The snapshot is not a merge, push or operational-receipt qualification.
 * Active PR review threads require the dedicated paginating connector tool.
 */
export async function collectPreflight({repository, fetchJson, activePr = null,
  fetchReviewThreads = null, now = () => new Date().toISOString(), maxPages = 20,
  persistObservation = null}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 100) throw Error("invalid pagination budget");
  if (!(activePr === null || (Number.isInteger(activePr) && activePr > 0))) throw Error("invalid owner PR");
  if (persistObservation !== null && typeof persistObservation !== "function") throw Error("invalid persistence capability");
  const prefix = `https://api.github.com/repos/${repository}`;
  async function get(suffix) {
    const url = prefix + suffix;
    let observation;
    try {
      const response = await fetchJson(url);
      const status = !response || response.error || Number(response.status) >= 400 ? "UNKNOWN" : "OBSERVED";
      observation = {url, observed_at: now(), status, response};
    } catch {
      observation = {url, observed_at: now(), status: "UNKNOWN", response: null};
    }
    // Persistence is outside the connector catch: a disk/host failure must stop
    // collection, not be converted into a successfully saved UNKNOWN record.
    if (persistObservation) await persistObservation(observation);
    return observation.status === "UNKNOWN" ? {...observation, response:null} : observation;
  }
  async function pages(suffix) {
    const observations = [];
    const items = [];
    for (let page = 1; page <= maxPages; page++) {
      const observation = await get(`${suffix}${suffix.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
      observations.push(observation);
      if (observation.status !== "OBSERVED" || !Array.isArray(observation.response)) return {status:"UNKNOWN", complete:false, observations};
      items.push(...observation.response);
      if (observation.response.length < 100) return {status:"OBSERVED", complete:true, items, observations};
    }
    return {status:"UNKNOWN", complete:false, observations};
  }
  const repo = await get("");
  if (repo.status !== "OBSERVED" || repo.response.full_name !== repository || !repo.response.default_branch) throw Error("repository observation unavailable");
  const branch = repo.response.default_branch;
  const defaultBranch = await get(`/branches/${encodeURIComponent(branch)}`);
  const rulesets = await pages("/rulesets?includes_parents=true");
  const openPullRequests = await pages("/pulls?state=open");
  const recentActions = await get("/actions/runs?per_page=20&page=1");
  let active = {status: "NOT_SELECTED", number: null};
  if (activePr !== null) {
    const pr = await get(`/pulls/${activePr}`);
    const reviews = await pages(`/pulls/${activePr}/reviews`);
    let threads = {status: "UNKNOWN", response: null};
    if (fetchReviewThreads) {
      try {
        // The host must preserve the connector's completeness metadata; a list
        // alone never establishes that all threads were observed.
        const response = await fetchReviewThreads(repository, activePr);
        threads = {status: response?.complete === true ? "OBSERVED" : "UNKNOWN", response, observed_at: now()};
      } catch { /* inaccessible thread details remain UNKNOWN */ }
    }
    if (persistObservation) await persistObservation({tool:"github_list_pull_request_review_threads",
      arguments:{repository_full_name:repository, pr_number:activePr}, observed_at:now(), ...threads});
    active = {number: activePr, pr, reviews, threads};
  }
  return {schema:"agent-work-preflight/v1", repository, generated_at:now(), repo,
    default_branch:defaultBranch, rulesets, open_pull_requests:openPullRequests,
    active_pull_request:active, recent_actions:recentActions,
    recent_actions_scope:"BOUNDED_INVENTORY_NOT_CI_QUALIFICATION",
    environments:"UNKNOWN_NOT_ACCESSED", authentication:"AUTHORIZED_HOST_RESPONSIBILITY",
    critical_unknown_blocks_binding:true, push_qualified:false};
}

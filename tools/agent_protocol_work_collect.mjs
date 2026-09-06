/** Read-only Work collector. Dependencies are supplied by the authorized host.
 * fetchJson(url): decoded JSON from the real GitHub connector GET tool.
 * saveBlob(sha, response): preserves the raw base64 blob response outside source.
 * hasBlob(sha): optional verified content-addressed cache; never skips final hashing.
 * This module has no token, HTTP client, publication or process API.
 */
export async function collectSource({repository, fetchJson, saveBlob,
  hasBlob = async () => false, now = () => new Date().toISOString(), maxCalls = 2000}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (!Number.isInteger(maxCalls) || maxCalls < 1 || maxCalls > 10000) throw Error("invalid connector call budget");
  if (typeof fetchJson !== "function" || typeof saveBlob !== "function") throw Error("connector host capabilities required");
  const prefix = `https://api.github.com/repos/${repository}`;
  let calls = 0;
  const observations = [];
  async function get(suffix) {
    if (++calls > maxCalls) throw Error("bounded connector call budget exhausted");
    const url = prefix + suffix;
    const response = await fetchJson(url);
    if (!response || typeof response !== "object" || response.error || Number(response.status) >= 400) {
      throw Error("connector observation unavailable; no inferred success");
    }
    const observation = {url, observed_at: now(), response};
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
  for (const sha of blobs.keys()) {
    if (await hasBlob(sha)) { cached++; continue; }
    const blob = (await get(`/git/blobs/${sha}`)).response;
    if (blob.sha !== sha || blob.encoding !== "base64") throw Error("lossless blob unavailable");
    await saveBlob(sha, blob);
    downloaded++;
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

/** Bounded observational preflight. Unknown policy/Actions remain UNKNOWN.
 * The snapshot is not a merge, push or operational-receipt qualification.
 * Active PR review threads require the dedicated paginating connector tool.
 */
export async function collectPreflight({repository, fetchJson, activePr = null,
  fetchReviewThreads = null, now = () => new Date().toISOString(), maxPages = 20}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 100) throw Error("invalid pagination budget");
  if (!(activePr === null || (Number.isInteger(activePr) && activePr > 0))) throw Error("invalid owner PR");
  const prefix = `https://api.github.com/repos/${repository}`;
  async function get(suffix) {
    const url = prefix + suffix;
    try {
      const response = await fetchJson(url);
      if (!response || response.error || Number(response.status) >= 400) throw Error("unavailable");
      return {url, observed_at: now(), status: "OBSERVED", response};
    } catch {
      return {url, observed_at: now(), status: "UNKNOWN", response: null};
    }
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
    active = {number: activePr, pr, reviews, threads};
  }
  return {schema:"agent-work-preflight/v1", repository, generated_at:now(), repo,
    default_branch:defaultBranch, rulesets, open_pull_requests:openPullRequests,
    active_pull_request:active, recent_actions:recentActions,
    recent_actions_scope:"BOUNDED_INVENTORY_NOT_CI_QUALIFICATION",
    environments:"UNKNOWN_NOT_ACCESSED", authentication:"AUTHORIZED_HOST_RESPONSIBILITY",
    critical_unknown_blocks_binding:true, push_qualified:false};
}

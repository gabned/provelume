"""Execute the displayed Work bootstrap with synthetic connector responses."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "posix", reason="Work shell bootstrap uses POSIX quoting")
def test_documented_quickstart_in_fresh_host(tmp_path):
    node = shutil.which("node")
    assert node, "Node is required for Work conformance"
    guide = (ROOT / "docs/agent-development-v1.4.3-work.md").read_text()
    snippet = re.search(r"```javascript\n(.*?)\n```", guide, re.S).group(1)
    # Apostrophes, spaces and shell metacharacters must remain literal paths.
    canonical = tmp_path / "canonical ' $()"
    (canonical / "tools").mkdir(parents=True)
    module = canonical / "tools/agent_protocol_work_collect.mjs"
    shutil.copyfile(ROOT / "tools/agent_protocol_work_collect.mjs", module)
    evidence = tmp_path / "evidence ' $()"
    snippet = snippet.replace('"/absolute/canonical-core"', json.dumps(str(canonical)))
    snippet = snippet.replace('"/absolute/evidence/new-work-startup"', json.dumps(str(evidence)))
    snippet = snippet.replace('"gabned/provelume"', '"example/public"')
    harness = r"""
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {execSync} from 'node:child_process';
import {readFileSync, writeFileSync, mkdirSync, existsSync, rmSync} from 'node:fs';
import {dirname, join} from 'node:path';
const [snippet, evidence, module] = JSON.parse(readFileSync(0, 'utf8'));
const objectId = (kind, bytes) => createHash('sha1')
  .update(Buffer.from(`${kind} ${bytes.length}\0`)).update(bytes).digest('hex');
const bytes = Buffer.from([0, 128, 255, 10]);
const blob = objectId('blob', bytes);
const root = objectId('tree', Buffer.concat([
  Buffer.from('100644 binary.dat\0'), Buffer.from(blob, 'hex')]));
const base = objectId('commit', Buffer.from(`tree ${root}\n\nsynthetic fixture\n`));
const repo = 'example/public';
const replies = {
  '': {full_name:repo, default_branch:'main'},
  '/git/ref/heads/main': {ref:'refs/heads/main', object:{type:'commit', sha:base}},
  [`/git/commits/${base}`]: {sha:base, tree:{sha:root}},
  [`/git/trees/${root}?recursive=1`]: {sha:root, truncated:false,
    tree:[{path:'binary.dat', mode:'100644', type:'blob', sha:blob, size:bytes.length}]},
  '/branches/main': {name:'main', commit:{sha:base}, protected:false},
  '/rulesets?includes_parents=true&per_page=100&page=1': [],
  '/pulls?state=open&per_page=100&page=1': [],
  '/actions/runs?per_page=20&page=1': {workflow_runs:[]},
};
let calls = 0;
const tools = {
  exec_command: async ({cmd}) => {
    try { return {exit_code:0, output:execSync(cmd, {encoding:'utf8', stdio:'pipe'})}; }
    catch (error) { return {exit_code:error.status, output:String(error.stderr)}; }
  },
  apply_patch: async patch => {
    const pattern = /^\*\*\* Begin Patch\n\*\*\* Add File: ([^\n]+)\n\+([^\n]+)\n\*\*\* End Patch$/;
    const match = pattern.exec(patch);
    assert.ok(match, 'expected one complete JSON record');
    assert.ok(match[1].startsWith(evidence + '/'));
    mkdirSync(dirname(match[1]), {recursive:true});
    writeFileSync(match[1], match[2] + '\n', {flag:'wx'});
  },
  mcp__codex_apps__github_fetch: async ({url}) => {
    calls++;
    const prefix = `https://api.github.com/repos/${repo}`;
    assert.ok(url.startsWith(prefix));
    const response = replies[url.slice(prefix.length)];
    assert.notEqual(response, undefined, url);
    return {isError:false, structuredContent:{content:JSON.stringify(response)}};
  },
  mcp__codex_apps__github_fetch_file: async args => {
    calls++;
    assert.deepEqual(args,
      {repository_full_name:repo, path:'binary.dat', ref:base, encoding:'base64'});
    return {isError:false,
      structuredContent:{sha:blob, encoding:'base64', content:bytes.toString('base64')}};
  },
};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const execute = () => new AsyncFunction('tools', snippet)(tools);
await execute();
const record = name => JSON.parse(readFileSync(join(evidence, name + '.json'), 'utf8'));
assert.equal(record('snapshot').commit_sha, base);
assert.equal(record('snapshot').tree_sha, root);
assert.equal(record('local_preflight'), 'NOT_RUN');
assert.equal(record('push_qualified'), false);
assert.deepEqual(Buffer.from(record('records/' + blob).content, 'base64'), bytes);
assert.ok(record('acquisition').observations.some(row => row.tool === 'github_fetch_file'));
const completedCalls = calls;
await assert.rejects(execute(), /verified collector bootstrap failed/);
assert.equal(calls, completedCalls, 'existing evidence fails before connector access');
rmSync(evidence, {recursive:true});
writeFileSync(module, readFileSync(module, 'utf8') + '\n// tampered\n');
await assert.rejects(execute(), /verified collector bootstrap failed/);
assert.equal(calls, completedCalls, 'digest mismatch fails before connector access');
assert.equal(existsSync(evidence), false);
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", harness],
        input=json.dumps([snippet, str(evidence), str(module)]),
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

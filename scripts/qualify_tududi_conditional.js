/* One disposable local public-server capability probe; never a real account.
 * Run only inside the documented isolated Docker fixture. The database URL,
 * server source path and loopback HTTP target are closed; no remote target flag.
 * This intentionally tests whether a stale conditional request is rejected.
 */
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const publicCommit = 'e03bc361bc7fa49a475fca9952b345822d1d5f11';
assert.equal(process.env.CONCORDIA_SYNTHETIC_ONLY, publicCommit);
assert.equal(process.env.NODE_ENV, 'test');
assert.equal(process.env.DATABASE_URL,
    'postgres://concordia_fixture:synthetic@concordia-s15-postgres:5432/concordia_s15_fixture');
assert.equal(process.argv[2], '/app/backend');
const root = process.argv[2];
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const source = path.join(root, 'modules/tasks/routes.js');
assert.equal(sha(fs.readFileSync(source)),
    '0ddd89797d4c89e0968aadc7d6876f857f98452ece78f0a3dafc0b6ec8ce6782');

const report = {schema: 'concordia-tududi-conditional-probe/v1',
    public_commit: publicCommit, public_version: '2.1.0',
    route_sha256: sha(fs.readFileSync(source)), probe_sha256: sha(fs.readFileSync(__filename)),
    runtime: process.version, synthetic_data_only: true, real_account: 'NOT_RUN',
    hypothesis: 'A nonmatching strong If-Match prevents overwriting a newer due date',
    expected: {http_status: 412, due_date: '2026-11-09'}, result: 'NOT_RUN'};

async function main() {
    const app = require(path.join(root, 'app'));
    const {sequelize, User, Task} = require(path.join(root, 'models'));
    const {createApiToken} = require(path.join(root, 'modules/users/apiTokenService'));
    let server;
    try {
        await sequelize.sync({force: true}); // The exact dedicated synthetic DB was checked above.
        const user = await User.create({email: 'concordia-proof@example.invalid', timezone: 'UTC',
            password_digest: '$2b$10$DPcA0XSvK9FT04mLyKGza.uHb8d.bESwP.XdQfQ47.sKVT4fYzbP.'});
        const {rawToken} = await createApiToken({userId: user.id, name: 'Disposable fixture only'});
        const task = await Task.create({name: 'Synthetic conditional proof', user_id: user.id,
            due_date: new Date('2026-11-07T00:00:00Z'), due_has_time: false, status: 0});
        server = await new Promise(resolve => {
            const value = app.listen(0, '127.0.0.1', () => resolve(value));
        });
        const url = 'http://127.0.0.1:' + server.address().port + '/api/v1/task/' + task.uid;
        const request = async (method, body, extra = {}) => {
            const response = await fetch(url, {method, redirect: 'error',
                headers: {Authorization: 'Bearer ' + rawToken, 'Content-Type': 'application/json',
                    ...extra}, body: body === null ? undefined : JSON.stringify(body),
                signal: AbortSignal.timeout(15000)});
            return {status: response.status, etag: response.headers.get('etag'),
                body: await response.json()};
        };
        const initial = await request('GET', null);
        assert.equal(initial.status, 200);
        assert.equal(initial.body.due_date, '2026-11-07');
        const newer = await request('PATCH', {due_date: '2026-11-09'});
        assert.equal(newer.status, 200);
        assert.equal(newer.body.due_date, '2026-11-09');
        const stale = await request('PATCH', {due_date: '2026-11-08'},
            {'If-Match': '"concordia-predeclared-never-matching"'});
        const after = await request('GET', null);
        assert.equal(after.status, 200);
        report.observed = {initial_due_date: initial.body.due_date,
            newer_due_date: newer.body.due_date, stale_request_http_status: stale.status,
            final_due_date: after.body.due_date,
            initial_revision_sha256: sha(String(initial.body.updated_at)),
            newer_revision_sha256: sha(String(newer.body.updated_at)),
            sent_if_match: '"concordia-predeclared-never-matching"',
            etag_present: initial.etag !== null, sequelize_version_option: Task.options.version};
        report.result = stale.status === 412 && after.body.due_date === '2026-11-09'
            ? 'CONDITIONAL_PROBE_PASS_NOT_FULL_QUALIFICATION' : 'CONDITIONAL_PRIMITIVE_FAIL';
    } finally {
        if (server) await new Promise(resolve => server.close(resolve));
        await sequelize.close();
    }
}

const deadline = setTimeout(() => {
    report.result = 'UNKNOWN';
    console.log('CONCORDIA_CONDITIONAL_REPORT=' + JSON.stringify(report));
    process.exit(2);
}, 180000);
main().then(() => {
    clearTimeout(deadline);
    console.log('CONCORDIA_CONDITIONAL_REPORT=' + JSON.stringify(report));
    process.exit(0);
}, error => {
    clearTimeout(deadline);
    report.result = 'UNKNOWN';
    report.failure_type = error?.constructor?.name || 'Error';
    console.log('CONCORDIA_CONDITIONAL_REPORT=' + JSON.stringify(report));
    process.exit(2);
});

"""The diagnostic form driver must accept real redirects and retain the durable observation."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import httpx

from provelume.ai_runtime_diagnostics import native_failure
from scripts.custodia_ordinary import diagnostic_cancellation


def test_installed_diagnostic_uses_one_consent_and_one_cancel_with_303():
    hidden = ('<input type="hidden" name="csrf_token" value="csrf">'
              '<input type="hidden" name="mutation_nonce" value="nonce">'
              '<input type="hidden" name="instance_id" value="instance">')
    jobs, posts = [], []
    diagnostic = native_failure(
        {"phase": "native_prefill", "exit_code": None, "parent_termination": True},
        code="cancelled", cancellation="request_cancel")

    class Client:
        def get(self, path):
            text = hidden
            if path.startswith('/operations/ai?'):
                text = ('<form action="/operations/ai/control">' + hidden +
                        '<input type="hidden" name="job_id" value="job_synthetic">'
                        '<input type="hidden" name="revision" value="revision">'
                        '<input type="hidden" name="action" value="cancel"></form>')
            return httpx.Response(200, text=text, request=httpx.Request('GET', 'http://test'+path))

        def post(self, path, *, data):
            posts.append((path, data))
            if path.endswith('/verify-preview'):
                return httpx.Response(200, text=hidden+'<input type="hidden" name="ref" '
                                      'value="synthetic-ref">',
                                      request=httpx.Request('POST', 'http://test'+path))
            if path.endswith('/execute'):
                jobs.append({'id': 'job_synthetic', 'status': 'running', 'attempt': 1,
                             'ai': {'attempts': [{'phase': 'possible'}]}})
            else:
                assert data['action'] == 'cancel' and data['revision'] == 'revision'
                jobs[0]['status'] = 'cancelled'
                jobs[0]['ai']['attempts'][0]['native_failure'] = diagnostic
            return httpx.Response(303, request=httpx.Request('POST', 'http://test'+path))

    journal = SimpleNamespace(list_jobs=lambda **kw: copy.deepcopy(jobs))
    instance = SimpleNamespace(scheduler=SimpleNamespace(journal=journal))
    case = ({'task': 'summary-en'}, 'document', {'representation_id': 'representation',
            'outputs': [{'id': 'text'}], 'version': {'id': 'version'}})
    result = diagnostic_cancellation(Client(), instance, case, executing=lambda: True)
    assert result['status'] == 'OBSERVED' and result['native_failure'] == diagnostic
    assert len(posts) == 3 and result['attempts'] == 1

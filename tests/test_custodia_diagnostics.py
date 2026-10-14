"""The diagnostic form driver must accept real redirects and retain the durable observation."""
from __future__ import annotations

import copy
import importlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from provelume.ai_runtime_diagnostics import native_failure
from scripts.custodia_ordinary import diagnostic_cancellation


@pytest.mark.parametrize('status,phase,quiescent', [
    ('cancelled', 'possible', None),
    ('cancelled', 'released', True),
    ('manual_intervention', 'uncertain', False),
    ('unrecognized', 'unrecognized', 'unrecognized'),
])
def test_installed_diagnostic_uses_one_consent_and_one_cancel_with_303(
    status, phase, quiescent,
):
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
                jobs[0]['status'] = status
                jobs[0]['ai']['attempts'][0].update(
                    phase=phase, quiescent=quiescent, native_failure=diagnostic,
                )
            return httpx.Response(303, request=httpx.Request('POST', 'http://test'+path))

    journal = SimpleNamespace(list_jobs=lambda **kw: copy.deepcopy(jobs))
    instance = SimpleNamespace(scheduler=SimpleNamespace(journal=journal))
    case = ({'task': 'summary-en'}, 'document', {'representation_id': 'representation',
            'outputs': [{'id': 'text'}], 'version': {'id': 'version'}})
    result = diagnostic_cancellation(Client(), instance, case, executing=lambda: True)
    assert result['status'] == ('OBSERVED' if status == 'cancelled' else 'NOT_OBSERVED')
    assert result['native_failure'] == diagnostic
    assert len(posts) == 3 and result['attempts'] == 1
    assert result['settlement'] == {
        'job_status': status if status != 'unrecognized' else None,
        'attempt_phase': phase if phase != 'unrecognized' else None,
        'quiescent': quiescent if type(quiescent) is bool else None,
    }


@pytest.mark.parametrize('failure', ['warm', 'live', None])
def test_parent_death_phase_requires_completed_warmup_and_observed_live_worker(
    monkeypatch, failure,
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    prepare = importlib.import_module('scripts.qualify_custodia_installed').prepare_parent_death
    report, events = {'checks': {}}, []

    def warm():
        events.append('ordinary_self_test')
        if failure == 'warm':
            raise ValueError('model_operation')

    def live():
        events.append('external_live_worker')
        return failure != 'live'

    def save():
        events.append(report['phase'])

    if failure:
        with pytest.raises(ValueError, match=(
            'model_operation' if failure == 'warm' else 'unobserved_live_worker'
        )):
            prepare(report, warm=warm, live=live, save=save)
        assert report['phase'] == 'parent_death_prepare'
        assert 'parent_death' not in events
        if failure == 'warm':
            assert 'external_live_worker' not in events
    else:
        prepare(report, warm=warm, live=live, save=save)
        assert events == ['parent_death_prepare', 'ordinary_self_test',
                          'external_live_worker', 'parent_death']
    assert report['checks'] == {} and 'parent_death_seconds' not in report


@pytest.mark.parametrize('state', ['completed', 'failed'])
def test_ordinary_model_action_retains_timed_terminal_outcome_without_retry(monkeypatch, state):
    from scripts import custodia_ordinary as driver

    hidden = ''.join(f'<input type="hidden" name="{name}" value="synthetic">'
                     for name in ('csrf_token', 'mutation_nonce', 'instance_id', 'authority'))
    requests, report = [], {}
    ticks = iter([10.0, 10.1, 10.2, 10.25])
    monkeypatch.setattr(driver.time, 'monotonic', lambda: next(ticks))

    class Client:
        def get(self, path):
            requests.append(('GET', path))
            markup = hidden
            if len(requests) > 1:
                markup += (f'<div id="ai-model-operation" data-state="{state}" '
                           'data-action="self_test" data-error="timeout"></div>')
            return httpx.Response(200, text=markup,
                                  request=httpx.Request('GET', 'http://test' + path))

        def post(self, path, *, data):
            requests.append(('POST', path))
            return httpx.Response(303, request=httpx.Request('POST', 'http://test' + path))

    if state == 'failed':
        with pytest.raises(ValueError, match='model_operation'):
            driver.model_action(Client(), 'self_test', report)
    else:
        driver.model_action(Client(), 'self_test', report)
    assert len([r for r in requests if r[0] == 'POST']) == 1
    assert report['operation_history'] == [report['operations']['self_test']]
    assert report['operations']['self_test']['state'] == state
    assert report['operations']['self_test']['error'] == 'timeout'
    assert report['operations']['self_test']['elapsed_seconds'] == pytest.approx(.25)

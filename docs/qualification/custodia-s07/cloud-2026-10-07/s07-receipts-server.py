import json
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_representations import _seed, _implementation
from provelume.representations import RepresentationBundleManager
from provelume.web import create_app

root = Path(__file__).parent / 's07-visual-receipts-v2'
root.mkdir(exist_ok=True)
instance, version = _seed(root)
text = '<script>public</script> ada@example.test. Public orchid observation.\n'
RepresentationBundleManager(instance.store).materialize(
    version, recipe_id='s07-public-escape', recipe_version='1', recipe_settings={},
    output_payloads={'public.txt': ('text/plain', text.encode())},
    implementation=_implementation(), anchor_targets=({'kind': 'page', 'page': 1},),
    created_at='2026-10-07T00:00:00+00:00',
)
app = create_app(instance.root, shell_settings_file=root / 'shell.json')
document = instance.store.list_canonical('documents')[0]
(root / 'fixture.json').write_text(json.dumps({'document': document['id'], 'version': version, 'text_length': len(text)}))
from datetime import timedelta
from provelume.ai_contract import digest
from provelume.ai_job_contract import Quote
from provelume.ai_job_runtime import JobOutcome
from provelume.scheduler_model import instant_text, utc_instant
host = app.state.ai_setup
host.save({'mode': 'local'}, 0)
# Isolated fixture-owned evidence; never available in a product HTTP request.
host.local_evidence = digest('public-s07-synthetic-only')
host.enable()
class Transport:
    network_used = False
    def exchange(self, current, *, cancel):
        current().prepare()
        assert not cancel()
        return JobOutcome({'kind': 'untrusted_text', 'value': 'Public synthetic test.'}, units=10, micros=0, usage_source='LOCAL')
profiles = host.profiles(host.configuration())[0]
host.jobs.adapters = {profiles[0].fingerprint: Transport()}
now = utc_instant()
host.jobs.quotes = lambda fingerprint: Quote(fingerprint, 'USD', instant_text(now-timedelta(days=1)), instant_text(now+timedelta(days=1)), 0, 8448, digest('synthetic-zero-cost'), True)
ref, _ = host.preview_test()
host.approve(ref)
job = host.enqueue(ref)
assert host.instance.run_ai_job(job['id'])['status'] == 'succeeded'
ref, _ = host.preview_test()
host.approve(ref)
host.enqueue(ref)

uvicorn.run(app, host='127.0.0.1', port=8048)

import json
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_representations import _seed, _implementation
from provelume.representations import RepresentationBundleManager
from provelume.web import create_app

root = Path(__file__).parent / 's07-visual-final'
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
uvicorn.run(app, host='127.0.0.1', port=8047)

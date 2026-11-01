"""Dedicated frozen OCR console process; never dispatch through the GUI."""
import json
import sys

from provelume.build_info import current_build_info
from provelume.ocr_render_worker import main

if sys.argv[1:] == ["--identity"]:
    print(json.dumps(current_build_info(), sort_keys=True))
    raise SystemExit(0)

raise SystemExit(main())

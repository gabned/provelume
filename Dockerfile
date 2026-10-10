# syntax=docker/dockerfile:1
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ARG PROVELUME_SOURCE_COMMIT=""
ARG SOURCE_DATE_EPOCH=""
LABEL org.opencontainers.image.source="https://github.com/gabned/provelume" \
      org.opencontainers.image.revision=$PROVELUME_SOURCE_COMMIT

COPY pyproject.toml README.md LICENSE COMMERCIAL-LICENSE.md ./
COPY core ./core
COPY scripts/stage_ai_runtime_inputs.py ./scripts/stage_ai_runtime_inputs.py
COPY build/native/windows.zip build/native/linux.zip /native-inputs/
RUN python scripts/stage_ai_runtime_inputs.py --source /app \
      --windows /native-inputs/windows.zip --linux /native-inputs/linux.zip \
    && rm -rf /native-inputs
RUN PYTHONPATH=core python - <<'PY'
import json, os
from pathlib import Path
from provelume import __version__
from provelume.build_info import create_build_info
epoch = os.environ.get("SOURCE_DATE_EPOCH")
identity = create_build_info(version=__version__,
    commit=os.environ.get("PROVELUME_SOURCE_COMMIT") or None, tag=None,
    channel="development", source_date_epoch=int(epoch) if epoch else None, official=False)
Path("core/provelume/build_info.json").write_text(json.dumps(identity, sort_keys=True) + "\n")
PY
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 provelume \
    && mkdir -p /instance /.instance.provelume/ai-models \
    && chown -R provelume:provelume /instance /.instance.provelume \
    && chmod 700 /.instance.provelume /.instance.provelume/ai-models

USER provelume
VOLUME ["/instance", "/.instance.provelume"]
EXPOSE 8000

CMD ["provelume", "serve", "/instance", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE COMMERCIAL-LICENSE.md ./
COPY core ./core
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 provelume \
    && mkdir -p /instance \
    && chown -R provelume:provelume /instance

USER provelume
VOLUME ["/instance"]
EXPOSE 8000

CMD ["provelume", "serve", "/instance", "--host", "0.0.0.0", "--port", "8000"]

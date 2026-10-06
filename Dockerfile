# The MCP tool server, served over Streamable HTTP for ElevenAgents or Cloud Run.
# Only the server's dependencies are installed: no model SDK and no API key, so a
# compromised container cannot call a model. Runs as a non-root user.

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements/server.txt requirements/server.txt
RUN pip install --prefix=/install -r requirements/server.txt
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --prefix=/install --no-deps .
# The data is generated from a fixed seed, so every build contains the same database.
RUN PYTHONPATH=/install/lib/python3.12/site-packages \
    python -m finance_ops.data.generate --out /build/data/finance_ops.sqlite

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /install /usr/local
COPY --from=build /build/data/finance_ops.sqlite /app/data/finance_ops.sqlite
ENV FINANCE_OPS_DB=/app/data/finance_ops.sqlite \
    PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/healthz', timeout=2)"
# MCP_AUTH_TOKEN must be supplied at run time; the server refuses to start without it.
CMD ["python", "-m", "finance_ops.server", "--transport", "http", "--host", "0.0.0.0"]

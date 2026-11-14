# One container: open-source HydraDB 0.4.0 (local-directory object store) + the Unstale app, for hosts that run a single container
# (Hugging Face Spaces, Fly, Render, a plain `docker run`). The graph is rebuilt at start from the dataset and
# the committed extraction cache, so no API key is needed.
#
#   docker build -t unstale .
#   docker run --rm -p 7860:7860 unstale        # then open http://localhost:7860
FROM ghcr.io/hydra-db/hydradb:0.4.0
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/python -c "import tomllib;p=tomllib.load(open('pyproject.toml','rb'))['project'];print(chr(10).join(p['dependencies']+p['optional-dependencies']['mcp']))" > /tmp/req.txt \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/req.txt \
 && rm -rf /root/.cache

COPY unstale ./unstale
COPY data/northwind.json ./data/northwind.json
COPY data/cache/llm ./data/cache/llm
COPY eval/*.json ./eval/
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh && chmod -R a+rwX /app/data

ENV PYTHONUNBUFFERED=1 PORT=7860
EXPOSE 7860
ENTRYPOINT ["/app/start.sh"]

#!/bin/sh
# Start MinIO, HydraDB, then the Unstale API in one container. Everything lives under $DATA and is rebuilt on start.
set -e
DATA="${DATA_DIR:-/tmp/unstale-data}"
rand() { head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
export MINIO_ROOT_USER=unstale MINIO_ROOT_PASSWORD="$(rand 16)"
TOKEN="$(rand 24)"
mkdir -p "$DATA/minio" "$DATA/hydra/cache"
printf '%s\n' "$TOKEN" > "$DATA/hydra/auth-token"

minio server "$DATA/minio" --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 > "$DATA/minio.log" 2>&1 &
until mc alias set local http://127.0.0.1:9000 unstale "$MINIO_ROOT_PASSWORD" > /dev/null 2>&1; do sleep 1; done
mc mb -p local/unstale-graph > /dev/null

env CLOUD_PROVIDER=aws AWS_BUCKET_NAME=unstale-graph AWS_DEFAULT_REGION=us-east-1 \
    AWS_ENDPOINT=http://127.0.0.1:9000 AWS_ALLOW_HTTP=true \
    AWS_ACCESS_KEY_ID=unstale AWS_SECRET_ACCESS_KEY="$MINIO_ROOT_PASSWORD" \
    GRAPH_NAMESPACE=default GRAPH_ID=default GRAPH_CELL_ID=cell-0 GRAPH_CELLS=cell-0 GRAPH_NODE_ID=node-0 \
    GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687 GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687 \
    GRAPH_DATA_CACHE_DIR="$DATA/hydra/cache" GRAPH_AUTH_TOKEN_FILE="$DATA/hydra/auth-token" \
    GRAPH_ALLOW_PLAINTEXT=true RUST_MIN_STACK=33554432 RUST_LOG=warn \
    graph-node > "$DATA/hydradb.log" 2>&1 &

# Wait for the Bolt port, then let the API ingest the dataset into a fresh namespace and serve it.
until /opt/venv/bin/python -c "import socket;socket.create_connection(('127.0.0.1',7687),1).close()" 2> /dev/null; do sleep 1; done
export UNSTALE_STORE=hydradb UNSTALE_HYDRA_URI=bolt://127.0.0.1:7687 UNSTALE_HYDRA_TOKEN="$TOKEN" \
       UNSTALE_BUILD_ON_START=1 UNSTALE_HOSTED=1 PYTHONPATH=/app
cd /app
exec /opt/venv/bin/uvicorn unstale.api:app --host 0.0.0.0 --port "${PORT:-7860}"

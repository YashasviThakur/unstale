#!/bin/sh
# Publish the single-container build (real HydraDB 0.4.0) as a free Hugging Face Space.
#
#   hf auth login                 # once, with a token that can write
#   sh deploy/space.sh <hf-username>
#
# Prints the Space URL. First build takes a few minutes; after that the app is up about 15 seconds after a start.
set -e
USER_NAME="${1:?usage: sh deploy/space.sh <hf-username>}"
SPACE="$USER_NAME/unstale"
STAGE="${STAGE_DIR:-$(mktemp -d)}"
mkdir -p "$STAGE/data/cache" "$STAGE/eval"
cp -r Dockerfile pyproject.toml unstale deploy "$STAGE/"
cp data/northwind.json "$STAGE/data/"
cp -r data/cache/llm "$STAGE/data/cache/"
cp eval/*.json "$STAGE/eval/"
rm -f "$STAGE/deploy/space.sh"
cat > "$STAGE/README.md" <<'CARD'
---
title: Unstale
colorFrom: gray
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Who is working from an old version of the truth. On open-source HydraDB.
---

# Unstale

Search tells you what is true. Unstale tells you who doesn't know yet.

This Space runs the whole stack in one container: MinIO, the open-source **HydraDB 0.4.0** engine and the Unstale API and UI.
The graph is rebuilt from the dataset at start.

Source, benchmark and write-up: https://github.com/YashasviThakur/unstale
CARD
if [ "${STAGE_ONLY:-0}" = "1" ]; then echo "staged in $STAGE"; exit 0; fi
hf repos create "$SPACE" --type space --space-sdk docker --exist-ok
hf upload "$SPACE" "$STAGE" . --repo-type space --commit-message "Deploy Unstale on HydraDB 0.4.0"
echo "https://huggingface.co/spaces/$SPACE   (app: https://$(echo "$USER_NAME" | tr 'A-Z_' 'a-z-')-unstale.hf.space)"

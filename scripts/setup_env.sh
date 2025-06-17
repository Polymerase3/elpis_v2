#!/usr/bin/env bash
set -euo pipefail
# ——————————————————————————————————————————————
# setup_env.sh (placed in scripts/)
# 1) Creates (or updates) your Conda env
# 2) Prints instructions for next steps
# ——————————————————————————————————————————————

# Resolve paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

ENV_YML="$REPO_ROOT/environment_setup.yml"
ENV_NAME="elpis_v2"

# 1. Create or update the environment
echo "🔄 Updating Conda env from $ENV_YML"
conda env update --file "$ENV_YML" --prune

# 2. Activate in this shell
echo "⚡ Activating environment '$ENV_NAME'"
eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"

echo

echo "✅ Conda environment '$ENV_NAME' is ready!"
echo "   To activate later:    conda activate $ENV_NAME"
echo "   To deactivate:         conda deactivate"
echo

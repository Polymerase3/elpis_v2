#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# purge_db.sh  —  **DESTROYS** the PostgreSQL/TimescaleDB data volume or
# bind‑mount folder without recreating the stack.
#
#   • Stops Compose services
#   • Removes the volume `db_data` (if declared)
#   • Deletes the bind‑mount folder (default ./data/db)
#
#   You can then run your separate init script (e.g. setup_docker.sh) to bring
#   the database back up.
# -----------------------------------------------------------------------------
# Usage:
#   ./scripts/purge_db.sh         # interactive confirmation
#   ./scripts/purge_db.sh --force   # no prompt
# -----------------------------------------------------------------------------
set -euo pipefail

# Locate repo root and compose file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"

cd "$REPO_ROOT"

# Prompt unless --force is supplied
if [[ "${1:-}" != "--force" ]]; then
  read -rp $'⚠️  This will DELETE ALL database data (volume or ./data/db). Continue? [y/N] ' resp
  [[ "$resp" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

# Ensure docker compose v2
if docker compose version &>/dev/null; then
  COMPOSE="docker compose"
else
  echo "Error: Docker Compose v2 (docker compose) not found." >&2
  exit 1
fi

# Stop containers and remove volume(s)
echo "🔻 Stopping containers and removing volume(s)…"
$COMPOSE down -v

# If the project uses a bind‑mount folder rather than a named volume, remove it
DATA_DIR="${DATA_DIR:-$REPO_ROOT/data/db}"
if [[ -d "$DATA_DIR" ]]; then
  echo "🧹 Removing bind‑mount directory $DATA_DIR …"
  rm -rf "$DATA_DIR"
fi

echo "✅ Database data purged. Run your init script to rebuild a fresh instance."
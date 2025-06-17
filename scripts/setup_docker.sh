#!/usr/bin/env bash
set -euo pipefail
# ——————————————————————————————————————————————
# setup_docker.sh (placed in scripts/)
# 1) Checks Docker & Compose (using Docker Compose v2)
# 2) Ensures .env exists
# 3) Switches to repo root and runs Docker Compose to bootstrap db
# ——————————————————————————————————————————————

# 1. Check Docker availability and permissions
if ! command -v docker &> /dev/null; then
  echo "Error: 'docker' not found. Install Docker first." >&2
  exit 1
fi

# Test Docker socket access
if ! docker info &> /dev/null; then
  echo "Error: Unable to connect to Docker daemon. Try adding your user to the 'docker' group or run this script with 'sudo'." >&2
  exit 1
fi

# 2. Check for Compose support (docker compose)
if docker compose version &> /dev/null; then
  COMPOSE_CMD="docker compose"
else
  echo "Error: Docker Compose v2 ('docker compose') not found. Please install or enable it." >&2
  exit 1
fi

# 3. Determine paths and check .env and compose file exist
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$REPO_ROOT/.env"
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env missing in repo root. Create with POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB." >&2
  exit 1
fi
if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Error: docker-compose.yml missing in repo root." >&2
  exit 1
fi

# Warn if version attribute exists (optional)
if grep -q '^version:' "$COMPOSE_FILE"; then
  echo "Warning: 'version:' attribute in docker-compose.yml is obsolete. Consider removing it to avoid confusion." >&2
fi

# 4. Bootstrap the PostgreSQL service
cd "$REPO_ROOT"
echo "⬇️  Pulling PostgreSQL image..."
$COMPOSE_CMD pull db

echo "⚙️  Starting PostgreSQL..."
$COMPOSE_CMD up -d db

echo
# Read environment values
POSTGRES_DB="$(grep '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2)"
POSTGRES_USER="$(grep '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2)"

echo "✅ PostgreSQL is up locally!"
echo "   • Host: localhost:5432"
echo "   • DB: $POSTGRES_DB"
echo "   • User: $POSTGRES_USER"
echo

echo "Logs:   $COMPOSE_CMD logs -f db"
echo "Stop:   $COMPOSE_CMD down"

echo
# ------------------------------------------------------------------------------
# To connect to the database from your local workstation:
#   psql "postgresql://$POSTGRES_USER:YOUR_PASSWORD@localhost:5432/$POSTGRES_DB"
# GUI client settings:
#   Host: localhost   Port: 5432   Database: $POSTGRES_DB   User: $POSTGRES_USER
# ------------------------------------------------------------------------------

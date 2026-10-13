#!/bin/sh
set -eu
: "${PORTKEY_API_KEY:?Set PORTKEY_API_KEY as a private service secret}"
: "${CAMPUS_CUSTOMS_ACCESS_USERNAME:?Set CAMPUS_CUSTOMS_ACCESS_USERNAME}"
: "${CAMPUS_CUSTOMS_ACCESS_PASSWORD:?Set CAMPUS_CUSTOMS_ACCESS_PASSWORD}"

mkdir -p "$CAMPUS_CUSTOMS_STATE_DIR"
working_db="$CAMPUS_CUSTOMS_STATE_DIR/campus_customs_new.db"
if [ ! -f "$working_db" ]; then
  cp /app/data/campus_customs.db "$working_db"
fi

export CAMPUS_CUSTOMS_AUDIT_PATH="${CAMPUS_CUSTOMS_AUDIT_PATH:-$CAMPUS_CUSTOMS_STATE_DIR/audit_trail.jsonl}"
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"

# 0005 — Local PostgreSQL without Docker for development

**Status:** accepted

**Context.** The development machine is short of disk space, and Docker Desktop's VM image is
large. PostgreSQL 18 is installed natively.

**Decision.** `scripts/dev_db.py` runs a project-local cluster: trust auth on localhost only,
port 5433, data in `%LOCALAPPDATA%/pramana/pgdata`, kept outside the OneDrive-synced repository
because syncing a live data directory corrupts it. Docker remains an option for server
deployment, not a requirement for development.

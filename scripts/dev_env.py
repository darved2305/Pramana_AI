"""Create a local .env with freshly generated keys (keeps any existing GNANI_API_KEY)."""

from __future__ import annotations

import secrets
from pathlib import Path

from pramana_contracts.tokens import generate_private_key_b64, private_key_from_b64, public_key_b64

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    env_path = ROOT / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    private = generate_private_key_b64()
    values = {
        "SIM_OPERATOR_KEY": secrets.token_urlsafe(24),
        "PARTICIPANT_SIGNING_KEY": private,
        "SIM_PARTICIPANT_PUBLIC_KEY": public_key_b64(private_key_from_b64(private)),
        "SIM_ORACLE_KEY": secrets.token_urlsafe(24),
        "CORE_AUTOMATION_KEY": secrets.token_urlsafe(24),
    }
    # A new checkout gets a unique database, never the shared default database.
    if not env_path.exists():
        db_name = "pramana_dev_" + secrets.token_hex(6)
        values["DATABASE_URL"] = f"postgresql+asyncpg://pramana@localhost:5433/{db_name}"
        values["PRAMANA_DB_NAMES"] = db_name

    if env_path.exists():
        # Retain every existing line, including unknown settings and comments.
        out = env_path.read_text(encoding="utf-8").splitlines()
        present = set(existing)
        for index, line in enumerate(out):
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in values and not existing.get(key):
                out[index] = f"{key}={values[key]}"
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key and not key.startswith("#") and key not in present:
                out.append(f"{key}={values[key]}" if key in values else line)
    else:
        out = []
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            out.append(f"{key}={values[key]}" if key in values else line)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {env_path} (secrets not printed)")


if __name__ == "__main__":
    main()

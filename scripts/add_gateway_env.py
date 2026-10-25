"""Upgrade a Milestone 1 local .env without changing existing database credentials."""

import secrets
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def main() -> None:
    path = Path(".env")
    if not path.is_file():
        raise SystemExit("Create the local .env with scripts/dev_env.py first.")
    values = dotenv_values(path)
    keys = ("GATEWAY_PASSWORD", "GATEWAY_DATABASE_URL", "TEST_GATEWAY_DATABASE_URL")
    if all(values.get(key) for key in keys):
        print("Gateway settings already present; no values changed.")
        return
    if any(key in values for key in keys):
        raise SystemExit(
            "Partial gateway settings exist; complete them locally without replacing credentials."
        )
    runtime = make_url(values.get("DATABASE_URL") or "")
    if runtime.host != "127.0.0.1" or runtime.port != 55432 or runtime.database != "loanshark":
        raise SystemExit("This helper is only for the local Compose development environment.")
    password = secrets.token_hex(24)
    gateway = runtime.set(username="loanshark_gateway", password=password)
    content = path.read_text() + "\nGATEWAY_PASSWORD=" + password + "\n"
    content += "GATEWAY_DATABASE_URL=" + gateway.render_as_string(hide_password=False) + "\n"
    content += (
        "TEST_GATEWAY_DATABASE_URL="
        + gateway.set(database="loanshark_test").render_as_string(hide_password=False)
        + "\n"
    )
    path.write_text(content)
    path.chmod(0o600)
    print("Added local gateway settings without displaying or changing existing secrets.")


if __name__ == "__main__":
    main()

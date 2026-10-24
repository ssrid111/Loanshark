"""Generate only local development database secrets; never overwrite an existing .env."""

import secrets
from pathlib import Path


def main() -> None:
    target = Path(".env")
    replacements = {
        "REPLACE_ADMIN_PASSWORD": secrets.token_hex(24),
        "REPLACE_MIGRATION_PASSWORD": secrets.token_hex(24),
        "REPLACE_RUNTIME_PASSWORD": secrets.token_hex(24),
    }
    content = Path(".env.example").read_text()
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    # Exclusive creation prevents accidental replacement of existing local settings.
    with target.open("x") as handle:
        handle.write(content)
    target.chmod(0o600)
    print("Created local .env with generated development database passwords (not displayed).")


if __name__ == "__main__":
    main()

"""Migrate a deliberately named test DB; never infer it from the runtime database."""

import os
import subprocess
import sys

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


def main() -> None:
    load_dotenv()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise SystemExit("Set TEST_DATABASE_URL explicitly before migrating tests.")
    try:
        parsed = make_url(url)
        if parsed.drivername != "postgresql+asyncpg" or not (parsed.database or "").endswith(
            "_test"
        ):
            raise ValueError
    except Exception:
        raise SystemExit("Refusing to migrate a database not explicitly named *_test.") from None
    environment = {**os.environ, "MIGRATION_DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], env=environment, check=True
    )


if __name__ == "__main__":
    main()

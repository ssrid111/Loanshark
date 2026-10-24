"""Create local development roles/databases explicitly; never reset existing passwords."""

import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    load_dotenv()
    admin_password = os.environ["POSTGRES_PASSWORD"]
    passwords = {
        "loanshark_migrator": os.environ["MIGRATION_PASSWORD"],
        "loanshark_runtime": os.environ["RUNTIME_PASSWORD"],
    }
    url = URL.create(
        "postgresql+asyncpg",
        username="loanshark_admin",
        password=admin_password,
        host="127.0.0.1",
        port=55432,
        database="postgres",
    )
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    try:
        async with engine.connect() as conn:
            for role, password in passwords.items():
                # PostgreSQL format() quotes identifiers/literals server-side. No user SQL.
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}
                )
                if not exists:
                    statement = await conn.scalar(
                        text(
                            "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L "
                            "NOSUPERUSER NOCREATEDB NOCREATEROLE', "
                            "CAST(:role AS text), CAST(:password AS text))"
                        ),
                        {"role": role, "password": password},
                    )
                    await conn.exec_driver_sql(statement)
            for name in ("loanshark", "loanshark_test"):
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
                )
                if not exists:
                    await conn.exec_driver_sql(f"CREATE DATABASE {name} OWNER loanshark_migrator")
                await conn.exec_driver_sql(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC")
                await conn.exec_driver_sql(f"GRANT CONNECT ON DATABASE {name} TO loanshark_runtime")
    finally:
        await engine.dispose()
    for name in ("loanshark", "loanshark_test"):
        engine = create_async_engine(url.set(database=name), hide_parameters=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
                await conn.execute(text("GRANT ALL ON SCHEMA public TO loanshark_migrator"))
                await conn.execute(text("GRANT USAGE ON SCHEMA public TO loanshark_runtime"))
        finally:
            await engine.dispose()
    print("Development roles and databases ready. Existing passwords were not changed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # No SQL, connection URL, or secret value in console failures.
        raise SystemExit(
            f"Database bootstrap failed ({type(exc).__name__}); check local setup."
        ) from None

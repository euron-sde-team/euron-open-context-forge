"""Command line: ``contextforge <command>``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from contextforge.core.config import get_settings


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "contextforge.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


def _worker(_: argparse.Namespace) -> None:
    from contextforge.worker import main

    asyncio.run(main())


def _migrate(_: argparse.Namespace) -> None:
    from contextforge.migrations.runner import upgrade

    upgrade(get_settings().database_url)
    print("migrations applied")


async def _create_owner(email: str, name: str, password: str) -> None:
    from sqlalchemy import func, select

    from contextforge.core.db import Database
    from contextforge.core.security import hash_password, password_problems
    from contextforge.users.models import User

    if problems := password_problems(password):
        sys.exit("password needs " + ", ".join(problems))
    db = Database(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        async with db.sessionmaker() as session:
            existing = await session.scalar(
                select(User).where(func.lower(User.email) == email.lower())
            )
            if existing:
                existing.role = "owner"
                existing.password_hash = hash_password(password)
                existing.disabled = False
                existing.session_version += 1
                print(f"updated {email} (owner)")
            else:
                session.add(
                    User(
                        email=email.lower(),
                        name=name,
                        role="owner",
                        password_hash=hash_password(password),
                    )
                )
                print(f"created {email} (owner)")
            await session.commit()
    finally:
        await db.dispose()


def _owner(args: argparse.Namespace) -> None:
    password = os.environ.get("CONTEXTFORGE_OWNER_PASSWORD") or getpass.getpass("Password: ")
    asyncio.run(_create_owner(args.email, args.name, password))


def _seed(args: argparse.Namespace) -> None:
    from contextforge.demo.seed import run

    asyncio.run(run(days=args.days, traffic=args.traffic, api_url=args.api_url))


def _bench(args: argparse.Namespace) -> None:
    from contextforge.benchmarks.__main__ import main as bench_main

    bench_main(
        ["run", "--runs", str(args.runs)]
        + (["--markdown", args.markdown] if args.markdown else [])
        + (["--json", args.json] if args.json else [])
    )


def _openapi(_: argparse.Namespace) -> None:
    from contextforge.openapi import spec, to_yaml

    sys.stdout.write(to_yaml(spec()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="contextforge", description="Euron Open ContextForge")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the API and gateway")
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 the container must listen on all interfaces
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "4330")))
    p.add_argument("--workers", type=int, default=int(os.environ.get("WEB_CONCURRENCY", "2")))
    p.set_defaults(fn=_serve)

    sub.add_parser("worker", help="run background jobs").set_defaults(fn=_worker)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=_migrate)
    sub.add_parser("openapi", help="print the OpenAPI document as YAML").set_defaults(fn=_openapi)

    p = sub.add_parser("create-owner", help="create or reset an owner account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Owner")
    p.set_defaults(fn=_owner)

    p = sub.add_parser("seed-demo", help="load demo configuration, history and live traffic")
    p.add_argument("--days", type=int, default=30, help="days of run history to backfill")
    p.add_argument("--traffic", type=int, default=40, help="live requests to send afterwards")
    p.add_argument(
        "--api-url", default=os.environ.get("CONTEXTFORGE_API_URL", "http://localhost:4330")
    )
    p.set_defaults(fn=_seed)

    p = sub.add_parser("benchmark", help="run the quality benchmark on the committed datasets")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--markdown")
    p.add_argument("--json")
    p.set_defaults(fn=_bench)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

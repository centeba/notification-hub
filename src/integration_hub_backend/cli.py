"""integration-hub CLI entry point.

Subcommands
-----------
start-api      Run the integration-api FastAPI service (port 8001)
start-email    Run the email-service FastAPI service (port 8002)
start-sms      Run the sms-service FastAPI service (port 8003)
start-webhook  Run the webhook-service FastAPI service (port 8004)
start-worker   Run the Temporal worker
migrate        Run Alembic migrations to head
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _add_uvicorn_flags(sub: argparse.ArgumentParser, default_port: int) -> None:
    sub.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    sub.add_argument("--host", default="0.0.0.0")
    # Railway (and any other PaaS that assigns a port dynamically) sets $PORT;
    # honour it over the service's compose-era default so a single image works
    # unmodified in both environments.
    sub.add_argument("--port", type=int, default=int(os.environ.get("PORT", default_port)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="integration-hub", description="Integration Hub CLI")
    subs = parser.add_subparsers(dest="command", metavar="COMMAND")

    api = subs.add_parser("start-api", help="Start the main orchestration API (port 8001)")
    _add_uvicorn_flags(api, default_port=8001)

    email = subs.add_parser("start-email", help="Start the email service (port 8002)")
    _add_uvicorn_flags(email, default_port=8002)

    sms = subs.add_parser("start-sms", help="Start the SMS service (port 8003)")
    _add_uvicorn_flags(sms, default_port=8003)

    webhook = subs.add_parser("start-webhook", help="Start the webhook service (port 8004)")
    _add_uvicorn_flags(webhook, default_port=8004)

    subs.add_parser("start-worker", help="Start the Temporal worker")

    subs.add_parser("start-mcp", help="Start the MCP server (stdio)")

    subs.add_parser("migrate", help="Run Alembic migrations to head")

    args = parser.parse_args()

    if args.command == "start-api":
        import uvicorn

        uvicorn.run(
            "integration_hub_backend.api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )

    elif args.command == "start-email":
        import uvicorn

        uvicorn.run(
            "integration_hub_backend.email.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )

    elif args.command == "start-sms":
        import uvicorn

        uvicorn.run(
            "integration_hub_backend.sms.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )

    elif args.command == "start-webhook":
        import uvicorn

        uvicorn.run(
            "integration_hub_backend.webhook.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )

    elif args.command == "start-worker":
        from integration_hub_backend.api.temporal.worker import run_worker

        asyncio.run(run_worker())

    elif args.command == "start-mcp":
        from integration_hub_backend.mcp.server import run

        asyncio.run(run())

    elif args.command == "migrate":
        _run_migrate()

    else:
        parser.print_help()
        sys.exit(1)


def _run_migrate() -> None:
    from alembic import command
    from alembic.config import Config

    # Prefer alembic.ini next to the installed package; fall back to cwd
    candidates = [
        Path(__file__).parent.parent.parent.parent / "alembic.ini",  # editable install
        Path(__file__).parent.parent.parent / "alembic.ini",
        Path.cwd() / "alembic.ini",
    ]
    alembic_ini = next((p for p in candidates if p.is_file()), None)
    if not alembic_ini:
        print("ERROR: Could not locate alembic.ini", file=sys.stderr)
        sys.exit(1)

    cfg = Config(str(alembic_ini))
    command.upgrade(cfg, "head")
    print("Database migrated to head.")


if __name__ == "__main__":
    main()

"""Inspect a reservation; apply only usage verified against the provider."""

import argparse
import asyncio

from app.infra.config.settings import Settings
from app.infra.db.repositories.governance import tokens
from app.infra.db.session import configure_database, get_engine, get_session_factory


async def run(args):
    configure_database(Settings.from_env())
    try:
        async with get_session_factory()() as db:
            record = await tokens.get_reservation(db, args.reservation_id)
            if record is None:
                raise ValueError("Reservation not found.")
            print(
                f"state={record.state} period={record.period} reserved={record.reserved_tokens} charged={record.charged_tokens}"
            )
            if args.apply:
                if record.state == "settled":
                    raise ValueError("Reservation is already settled.")
                await tokens.settle(db, record.id, args.actual_tokens)
                await db.commit()
                print("Usage reconciled.")
    finally:
        await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--reservation-id", required=True)
    parser.add_argument("--actual-tokens", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and (args.actual_tokens is None or args.actual_tokens < 0):
        parser.error(
            "--apply requires a nonnegative --actual-tokens verified against the provider"
        )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

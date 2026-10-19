import argparse
import os

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.jobs import run_job
from app.models import User
from app.storage import sha256


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--name", default="local-owner")
    bootstrap.add_argument("--key-env", default="BID_BOOTSTRAP_API_KEY")
    run = sub.add_parser("run-job")
    run.add_argument("job_id")
    args = parser.parse_args()
    if args.command == "bootstrap":
        key = os.environ.get(args.key_env)
        if not key or len(key) < 24:
            parser.error(f"Set {args.key_env} to a random value of at least 24 characters")
        with SessionLocal.begin() as db:
            user = db.scalar(select(User).where(User.api_key_hash == sha256(key.encode())))
            if user is None:
                user = User(name=args.name, api_key_hash=sha256(key.encode()))
                db.add(user)
                db.flush()
            print(f"Bootstrap user ready: {user.id}")
    else:
        print(run_job(SessionLocal, args.job_id, get_settings()))


if __name__ == "__main__":
    main()

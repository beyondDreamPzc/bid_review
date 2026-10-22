import argparse
import os

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.jobs import run_job
from app.models import User,WebSession
from sqlalchemy import delete
from app.storage import sha256


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--name", default="local-owner")
    bootstrap.add_argument("--key-env", default="BID_BOOTSTRAP_API_KEY")
    bootstrap.add_argument("--preserve-existing-name",action="store_true",
        help="Compose bootstrap: preserve an existing named account after key rotation")
    run = sub.add_parser("run-job")
    run.add_argument("job_id")
    disable=sub.add_parser("set-user-status")
    disable.add_argument("user_id")
    disable.add_argument("--disabled",choices=["true","false"],required=True)
    args = parser.parse_args()
    if args.command == "bootstrap":
        key = os.environ.get(args.key_env)
        if not key or len(key) < 24:
            parser.error(f"Set {args.key_env} to a random value of at least 24 characters")
        with SessionLocal.begin() as db:
            user = db.scalar(select(User).where(User.api_key_hash == sha256(key.encode())))
            if user is None and args.preserve_existing_name:
                user=db.scalar(select(User).where(User.name==args.name).order_by(User.created_at,User.id).limit(1))
            if user is None:
                user = User(name=args.name, api_key_hash=sha256(key.encode()))
                db.add(user)
                db.flush()
            print(f"Bootstrap user ready: {user.id}")
    elif args.command=="set-user-status":
        with SessionLocal.begin() as db:
            user=db.get(User,args.user_id)
            if not user:parser.error("User not found")
            user.disabled=args.disabled=="true"
            db.execute(delete(WebSession).where(WebSession.user_id==user.id))
            print("Account status updated; existing browser sessions revoked")
    else:
        print(run_job(SessionLocal, args.job_id, get_settings()))


if __name__ == "__main__":
    main()

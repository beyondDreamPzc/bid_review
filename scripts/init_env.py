"""Generate local-only credentials; existing .env is never overwritten."""
import secrets
from pathlib import Path

path = Path(__file__).resolve().parent.parent / ".env"
if path.exists():
    print("Existing .env preserved")
else:
    values = {"MYSQL_ROOT_PASSWORD": secrets.token_hex(24),
              "MYSQL_PASSWORD": secrets.token_hex(24),
              "BID_BOOTSTRAP_API_KEY": secrets.token_urlsafe(36)}
    with path.open("x", encoding="utf-8") as stream:
        stream.write("# Local development credentials. Do not commit or share.\n")
        stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("Created local .env (credentials not printed)")

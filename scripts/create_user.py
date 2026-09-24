"""Create an organisation and its first user.

The migration deliberately ships no default account, so run this once after
`alembic upgrade head`:

    python scripts/create_user.py --email you@firm.com --org "Your Firm"

The password is read from a prompt, never from a command-line argument, so it does
not land in shell history or the process list.
"""
import argparse
import getpass
import sys

sys.path.insert(0, ".")

from app.database.session import SessionLocal  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import MAX_PASSWORD_BYTES, get_user_by_email, hash_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an organisation and its first user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None, help="Person's display name")
    parser.add_argument("--org", default=None, help="Organisation name; joins the existing one if omitted")
    parser.add_argument("--role", default="admin", choices=["admin", "member"])
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.")
        return 1
    if len(password) < 12:
        print("Use at least 12 characters.")
        return 1
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        print(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
        return 1

    db = SessionLocal()
    try:
        if get_user_by_email(db, email):
            print(f"A user with {email} already exists.")
            return 1

        if args.org:
            organisation = Organisation(name=args.org)
            db.add(organisation)
            db.flush()
        else:
            organisation = db.query(Organisation).order_by(Organisation.id).first()
            if organisation is None:
                print("No organisation exists yet. Pass --org to create one.")
                return 1

        db.add(User(
            org_id=organisation.id,
            email=email,
            password_hash=hash_password(password),
            name=args.name,
            role=args.role,
        ))
        db.commit()
        print(f"Created {email} ({args.role}) in organisation {organisation.id} '{organisation.name}'.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

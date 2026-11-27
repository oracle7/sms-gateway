import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from database import SessionLocal, init_db, utc_now
from models import User, UserSession
from services.audit import record_audit
from services.security import hash_password, validate_password_strength


def _prompt_password(provided: str | None) -> str:
    if provided:
        return provided
    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw1 != pw2:
        raise ValueError("Passwords do not match.")
    return pw1


def cmd_create_user(args, role_override: str | None = None) -> int:
    init_db()
    db = SessionLocal()
    try:
        username = args.username.strip().lower()
        role = role_override or args.role
        if db.query(User).filter(User.username == username).first():
            print(f"Error: user '{username}' already exists.", file=sys.stderr)
            return 1

        password = _prompt_password(args.password)
        validate_password_strength(password, settings.MIN_PASSWORD_LENGTH)

        user = User(
            username=username,
            display_name=args.display_name.strip(),
            role=role,
            password_hash=hash_password(password),
            is_active=True,
            must_change_password=bool(args.must_change_password),
        )
        db.add(user)
        db.flush()
        record_audit(
            db,
            action="admin.user_created",
            resource_type="user",
            resource_id=str(user.id),
            actor_username="cli",
            metadata={"target_username": username, "role": role},
            commit=False,
        )
        db.commit()
        print(f"Created {role} user '{username}' (id={user.id}).")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_reset_password(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        username = args.username.strip().lower()
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found.", file=sys.stderr)
            return 1

        password = _prompt_password(args.password)
        validate_password_strength(password, settings.MIN_PASSWORD_LENGTH)

        now = utc_now()
        user.password_hash = hash_password(password)
        user.failed_login_attempts = 0
        user.locked_until = None
        user.must_change_password = bool(args.must_change_password)

        active_sessions = (
            db.query(UserSession)
            .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .all()
        )
        for s in active_sessions:
            s.revoked_at = now
            s.revoked_reason = "cli_password_reset"

        record_audit(
            db,
            action="admin.user_password_reset",
            resource_type="user",
            resource_id=str(user.id),
            actor_username="cli",
            metadata={"target_username": username, "revoked_sessions": len(active_sessions)},
            commit=False,
        )
        db.commit()
        print(f"Password reset for '{username}' (revoked {len(active_sessions)} active session(s)).")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_unlock_user(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        username = args.username.strip().lower()
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found.", file=sys.stderr)
            return 1

        user.failed_login_attempts = 0
        user.locked_until = None
        record_audit(
            db,
            action="admin.user_unlocked",
            resource_type="user",
            resource_id=str(user.id),
            actor_username="cli",
            metadata={"target_username": username},
            commit=False,
        )
        db.commit()
        print(f"Unlocked user '{username}'.")
        return 0
    finally:
        db.close()


def cmd_list_users(_args) -> int:
    init_db()
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id.asc()).all()
        if not users:
            print("No users found.")
            return 0
        for u in users:
            status = "active" if u.is_active else "disabled"
            locked = f" locked_until={u.locked_until.isoformat()}" if u.locked_until else ""
            print(f"id={u.id} username={u.username} role={u.role} status={status} display_name={u.display_name!r}{locked}")
        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage SMS Gateway v3.0 users.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="Create an administrator account (Doctor).")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--display-name", required=True)
    p_admin.add_argument("--password", default=None)
    p_admin.add_argument("--must-change-password", action="store_true")

    p_user = sub.add_parser("create-user", help="Create a user account (admin or staff).")
    p_user.add_argument("--username", required=True)
    p_user.add_argument("--display-name", required=True)
    p_user.add_argument("--role", choices=["admin", "staff"], default="staff")
    p_user.add_argument("--password", default=None)
    p_user.add_argument("--must-change-password", action="store_true")

    p_reset = sub.add_parser("reset-password", help="Reset a user's password and revoke sessions.")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", default=None)
    p_reset.add_argument("--must-change-password", action="store_true")

    p_unlock = sub.add_parser("unlock-user", help="Clear failed login lockout for a user.")
    p_unlock.add_argument("--username", required=True)

    sub.add_parser("list-users", help="List all configured users.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "create-admin":
        return cmd_create_user(args, role_override="admin")
    if args.command == "create-user":
        return cmd_create_user(args)
    if args.command == "reset-password":
        return cmd_reset_password(args)
    if args.command == "unlock-user":
        return cmd_unlock_user(args)
    if args.command == "list-users":
        return cmd_list_users(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

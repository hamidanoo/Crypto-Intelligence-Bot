"""Create the first administrator (bootstrap).

Usage, from the backend directory:

    ADMIN_BOOTSTRAP_USERNAME=admin ADMIN_BOOTSTRAP_PASSWORD='<secret>' \\
        python scripts/create_admin.py

The username and password come from the environment only.
There is no default password and no hardcoded credential.
The script refuses to run if any Super Admin already
exists, so it cannot be used to accidentally create a
second bootstrap administrator or overwrite one. The
password is never printed. After bootstrap, change the
password through the dashboard and rotate it regularly;
this bootstrap account should be used only to create
named administrator accounts, then secured.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth.passwords import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AdminRole, AdminUser, AdminUserRole  # noqa: E402


def main() -> int:
    username = os.environ.get("ADMIN_BOOTSTRAP_USERNAME", "").strip()
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    email = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", f"{username}@localhost").strip()
    if not username or not password:
        print(
            "ADMIN_BOOTSTRAP_USERNAME and ADMIN_BOOTSTRAP_PASSWORD must both be set.",
            file=sys.stderr,
        )
        return 2
    if len(password) < 8:
        print("Bootstrap password must be at least 8 characters.", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        existing_super = (
            db.query(AdminUser)
            .filter(AdminUser.is_superuser.is_(True), AdminUser.is_active.is_(True))
            .first()
        )
        if existing_super is not None:
            print(
                "A Super Admin already exists; bootstrap refuses to create another one.",
                file=sys.stderr,
            )
            return 3
        if db.query(AdminUser).filter(AdminUser.username == username).first():
            print("That username already exists.", file=sys.stderr)
            return 3
        user = AdminUser(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role="super_admin",
            is_active=True,
            is_superuser=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        role = db.query(AdminRole).filter(AdminRole.name == "super_admin").first()
        if role is not None:
            db.add(AdminUserRole(admin_user_id=user.id, role_id=role.id))
            db.commit()
        print(f"Super Admin '{username}' created successfully.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

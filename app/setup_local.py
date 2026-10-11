"""Initialize local tables and provision the installation's pharmacist account."""

import argparse
from getpass import getpass

from sqlalchemy import update

from app.database import Base, SessionLocal, engine
from app.migrations import migrate_employee_table
from app.models import PharmacistProfile
from app.services.security import hash_secret
from app.services.settings import seed_settings


def provision_account(db, email: str, password: str) -> None:
    email = email.strip().lower()
    if len(email) > 150 or email.count('@') != 1 or any(c.isspace() for c in email):
        raise ValueError("Enter a valid email address")
    if not all(email.split('@')):
        raise ValueError("Enter a valid email address")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12 to 128 characters")
    # Conditional update prevents concurrent setup from replacing an existing password.
    result = db.execute(update(PharmacistProfile).where(
        PharmacistProfile.id == 1, PharmacistProfile.password_hash.is_(None),
    ).values(email=email, password_hash=hash_secret(password)))
    if result.rowcount != 1:
        db.rollback()
        raise ValueError("Account is already configured; use the authenticated password-change API")
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', help='Email for the initial pharmacist account')
    args = parser.parse_args()
    migrate_employee_table(engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_settings(db)
        if not args.email:
            print('Local database and tables initialized. Use --email to configure login.')
            return
        if db.get(PharmacistProfile, 1).password_hash:
            parser.error('Account is already configured; use the authenticated password-change API')
        password = getpass('New password (12–128 characters): ')
        if password != getpass('Confirm password: '):
            parser.error('Passwords do not match')
        try:
            provision_account(db, args.email, password)
        except ValueError as exc:
            parser.error(str(exc))
    print('Local pharmacist account configured. You can now log in.')


if __name__ == '__main__':
    main()

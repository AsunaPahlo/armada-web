#!/usr/bin/env python3
"""
Migration script to add lockout fields to the users table.
Run this script once after updating the code to add the new columns.

Usage:
    python scripts/migrate_user_lockout.py
"""
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text


def migrate():
    """Add lockout columns to users table."""
    app = create_app()

    with app.app_context():
        # Check if columns already exist
        result = db.session.execute(text("PRAGMA table_info(users)"))
        columns = [row[1] for row in result.fetchall()]

        migrations_needed = []

        if 'failed_login_attempts' not in columns:
            migrations_needed.append(
                "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0"
            )

        if 'locked_until' not in columns:
            migrations_needed.append(
                "ALTER TABLE users ADD COLUMN locked_until DATETIME"
            )

        if 'last_failed_login' not in columns:
            migrations_needed.append(
                "ALTER TABLE users ADD COLUMN last_failed_login DATETIME"
            )

        if not migrations_needed:
            print("All lockout columns already exist. No migration needed.")
            return

        print(f"Adding {len(migrations_needed)} new column(s) to users table...")

        for sql in migrations_needed:
            print(f"  Executing: {sql}")
            db.session.execute(text(sql))

        db.session.commit()
        print("Migration completed successfully!")


if __name__ == '__main__':
    migrate()

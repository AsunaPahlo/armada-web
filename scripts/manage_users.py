#!/usr/bin/env python3
"""
User management CLI for Armada.

Commands:
    reset-password <username> [password]  - Reset a user's password
    unlock <username>                     - Unlock a locked account
    list                                  - List all users

Usage from Docker:
    docker exec armada python scripts/manage_users.py reset-password admin
    docker exec armada python scripts/manage_users.py reset-password admin mynewpass
    docker exec armada python scripts/manage_users.py unlock admin
    docker exec armada python scripts/manage_users.py list
"""
import os
import sys
import secrets
import string

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.user import User


def generate_password(length=12):
    """Generate a random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def reset_password(username, new_password=None):
    """Reset a user's password."""
    user = User.query.filter(User.username.ilike(username)).first()

    if not user:
        print(f"Error: User '{username}' not found.")
        return False

    if not new_password:
        new_password = generate_password()

    if len(new_password) < 4:
        print("Error: Password must be at least 4 characters.")
        return False

    user.set_password(new_password)
    user.unlock()  # Also unlock the account
    db.session.commit()

    print(f"Password reset for user '{user.username}'.")
    print(f"New password: {new_password}")
    return True


def unlock_user(username):
    """Unlock a user's account."""
    user = User.query.filter(User.username.ilike(username)).first()

    if not user:
        print(f"Error: User '{username}' not found.")
        return False

    if not user.is_locked and user.failed_login_attempts == 0:
        print(f"User '{user.username}' is not locked.")
        return True

    user.unlock()
    print(f"Account '{user.username}' has been unlocked.")
    return True


def list_users():
    """List all users."""
    users = User.query.order_by(User.username).all()

    if not users:
        print("No users found.")
        return

    print(f"\n{'Username':<20} {'Role':<10} {'Status':<15}")
    print("-" * 45)

    for user in users:
        if user.is_locked:
            status = "LOCKED"
        elif user.failed_login_attempts > 0:
            status = f"{user.failed_login_attempts}/5 attempts"
        else:
            status = "OK"

        print(f"{user.username:<20} {user.role:<10} {status:<15}")

    print(f"\nTotal: {len(users)} user(s)")


def print_usage():
    """Print usage information."""
    print(__doc__)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    app = create_app()

    with app.app_context():
        if command == 'reset-password':
            if len(sys.argv) < 3:
                print("Usage: manage_users.py reset-password <username> [password]")
                sys.exit(1)
            username = sys.argv[2]
            password = sys.argv[3] if len(sys.argv) > 3 else None
            success = reset_password(username, password)
            sys.exit(0 if success else 1)

        elif command == 'unlock':
            if len(sys.argv) < 3:
                print("Usage: manage_users.py unlock <username>")
                sys.exit(1)
            username = sys.argv[2]
            success = unlock_user(username)
            sys.exit(0 if success else 1)

        elif command == 'list':
            list_users()
            sys.exit(0)

        else:
            print(f"Unknown command: {command}")
            print_usage()
            sys.exit(1)


if __name__ == '__main__':
    main()

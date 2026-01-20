#!/usr/bin/env python3
"""
Add performance indexes to existing database tables.

Run this script once after updating to add the new composite indexes
that improve query performance for large datasets.

Usage:
    python scripts/add_performance_indexes.py
"""
import sqlite3
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_db_path():
    """Get the database path from config or default."""
    # Try to import from app config
    try:
        from app import create_app
        app = create_app()
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if db_uri.startswith('sqlite:///'):
            return db_uri.replace('sqlite:///', '')
    except Exception:
        pass

    # Default path
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'armada.db')


def add_indexes(db_path: str):
    """Add composite indexes to improve query performance."""

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return False

    print(f"Adding performance indexes to {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # List of indexes to create
    indexes = [
        # VoyageLoot indexes
        ('ix_voyage_loot_fc_captured', 'voyage_loot', 'fc_id, captured_at'),
        ('ix_voyage_loot_submarine_captured', 'voyage_loot', 'submarine_name, captured_at'),

        # Voyage indexes
        ('ix_voyage_fc_return', 'voyages', 'fc_id, return_time'),
        ('ix_voyage_submarine_return', 'voyages', 'submarine_name, return_time'),

        # DailyStats indexes (if needed)
        ('ix_daily_stats_fc_date', 'daily_stats', 'fc_id, stats_date'),
    ]

    created = 0
    skipped = 0

    for index_name, table_name, columns in indexes:
        try:
            # Check if index already exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,)
            )
            if cursor.fetchone():
                print(f"  [SKIP] {index_name} already exists")
                skipped += 1
                continue

            # Check if table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if not cursor.fetchone():
                print(f"  [SKIP] Table {table_name} does not exist")
                skipped += 1
                continue

            # Create the index
            sql = f"CREATE INDEX {index_name} ON {table_name} ({columns})"
            cursor.execute(sql)
            print(f"  [OK] Created {index_name} on {table_name}({columns})")
            created += 1

        except sqlite3.Error as e:
            print(f"  [ERROR] Failed to create {index_name}: {e}")

    conn.commit()
    conn.close()

    print(f"\nDone! Created {created} indexes, skipped {skipped}")
    return True


if __name__ == '__main__':
    db_path = get_db_path()

    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    add_indexes(db_path)

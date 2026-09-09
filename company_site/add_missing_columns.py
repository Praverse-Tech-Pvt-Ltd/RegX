"""Add the columns company_site's models declare but its database lacks.

The shipped `db.sqlite3` predates 134 model fields, so any query touching them
fails -- most visibly `AdminMaster.CustomUser.subscription_end_date`, which makes
every login return 500 while the login page itself renders fine.

Additive only. One `ALTER TABLE ... ADD COLUMN` per missing field, with the
column type taken from the field's own `db_type()` rather than hand-written SQL.
No existing row is modified, no column is dropped, no table is rebuilt.

Plain ALTER TABLE rather than Django's schema editor on purpose: the schema
editor rebuilds the whole table on SQLite, and that rebuild collides with an
existing index name on AdminMaster_customuser. ADD COLUMN is a native SQLite
operation that touches nothing else.

Back up db.sqlite3 before running. Re-running is safe: present columns are
skipped.

    docker compose exec -T company_site python add_missing_columns.py --dry-run
    docker compose exec -T company_site python add_missing_columns.py
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "RAAI.settings_integration")
django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import NOT_PROVIDED  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv

TEXTUAL = ("VARCHAR", "TEXT", "CHAR")


def default_clause(field, column_type):
    """SQL for a NOT NULL column's default.

    SQLite requires a default when adding a NOT NULL column to a table that has
    rows. Every such field here either declares a model default or sits on a
    table that is empty; the fallback below covers the latter.
    """
    value = field.default
    if value is NOT_PROVIDED:
        value = "" if column_type.upper().startswith(TEXTUAL) else 0
    elif callable(value):
        value = value()
    if isinstance(value, bool):
        value = 1 if value else 0
    if value is None:
        return " NULL"
    if isinstance(value, (int, float)):
        return " NOT NULL DEFAULT %s" % value
    return " NOT NULL DEFAULT '%s'" % str(value).replace("'", "''")


def main():
    existing_tables = set(connection.introspection.table_names())
    statements = []

    with connection.cursor() as cursor:
        for model in apps.get_models():
            table = model._meta.db_table
            if table not in existing_tables:
                continue
            present = {
                column.name
                for column in connection.introspection.get_table_description(cursor, table)
            }
            for field in model._meta.local_fields:
                if field.column in present:
                    continue
                column_type = field.db_type(connection)
                if column_type is None:  # non-concrete field
                    continue
                sql = 'ALTER TABLE "%s" ADD COLUMN "%s" %s' % (
                    table,
                    field.column,
                    column_type,
                )
                if not field.null:
                    sql += default_clause(field, column_type)
                statements.append((table, field.column, sql))

    if not statements:
        print("Nothing to add: the schema already matches the models.")
        return 0

    print("%d column(s) to add." % len(statements))
    if DRY_RUN:
        for table, column, sql in statements[:10]:
            print("  " + sql)
        if len(statements) > 10:
            print("  ... and %d more" % (len(statements) - 10))
        print("\nDry run: nothing was changed.")
        return 0

    added = failed = 0
    with connection.cursor() as cursor:
        for table, column, sql in statements:
            try:
                cursor.execute(sql)
                added += 1
            except Exception as exc:  # noqa: BLE001 - report and continue
                failed += 1
                print("  FAILED %s.%s: %s" % (table, column, str(exc)[:80]))

    print("Added %d column(s), %d failed." % (added, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

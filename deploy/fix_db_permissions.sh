#!/usr/bin/env bash
# Run this on the server whenever Cornote throws:
#   OperationalError: attempt to write a readonly database
#
# Cause: SQLite needs write access to BOTH db.sqlite3 AND its containing
# directory (it creates -journal/-wal/-shm files alongside the db on every
# write). If Apache/mod_wsgi runs as a different user than the one that
# deploys (git pull), the db file/directory aren't writable by the app.
#
# Fix: add the app's group to db.sqlite3 and the project directory, with
# setgid on the directory so files created by future deploys keep inheriting
# that group. This deliberately leaves the current owner (the deploy user)
# untouched - chown'ing ownership over to the app user instead would fix the
# app's write access but break the deploy user's, since they'd no longer own
# the directory or be in its group.
#
# Usage:
#   APP_GROUP=daemon ./deploy/fix_db_permissions.sh
#
# If you don't know which group Apache/mod_wsgi runs as, check:
#   grep -E '^(User|Group)' /opt/bitnami/apache/conf/httpd.conf
# or
#   ps aux | grep -i apache   # then: id <that user>

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_GROUP="${APP_GROUP:?Set APP_GROUP to the group Apache/mod_wsgi runs as, e.g. APP_GROUP=daemon}"

sudo chgrp "$APP_GROUP" "$PROJECT_DIR" "$PROJECT_DIR/db.sqlite3"
sudo chmod 2775 "$PROJECT_DIR"
sudo chmod 664 "$PROJECT_DIR/db.sqlite3"

echo "$PROJECT_DIR and db.sqlite3 are now group-writable by $APP_GROUP (owner unchanged)."

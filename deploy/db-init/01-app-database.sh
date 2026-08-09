#!/bin/sh
# First-boot provisioning for the application database.
#
# The postgres image already creates the POSTGRES_USER/PASSWORD/DB cluster
# from POSTGRES_* on first init. In addition, create the role and database
# named by the application's own DATABASE_URL (from backend/.env, exposed via
# the db service's optional env_file), so a fresh data directory always ends
# up with the exact credentials the app runs with - whatever backend/.env
# says. This script only runs on the first initialization of an empty data
# directory (docker-entrypoint-initdb.d semantics), and is idempotent: it is
# a no-op when the role and database already exist.
#
# The postgres entrypoint either executes initdb.d scripts or sources them
# when they are not executable, so all early returns go through a function
# (return, never exit) and the body must stay LF-terminated (see
# .gitattributes).
#
# Limitations: the DATABASE_URL password must not contain '@' or ':' (it is
# split off the URL with shell parameter expansion); identifiers are assumed
# to be plain ASCII without quotes.

set -e

main() {
    url="${DATABASE_URL:-}"
    [ -n "$url" ] || return 0

    rest="${url#*://}"
    [ "$rest" != "$url" ] || return 0

    creds="${rest%%@*}"
    [ "$creds" != "$rest" ] || return 0   # no credentials in URL -> nothing to create

    hostdb="${rest#*@}"
    db="${hostdb#*/}"
    db="${db%%/*}"      # trim any extra path segments
    db="${db%%\?*}"     # trim query string

    user="${creds%%:*}"
    pass="${creds#*:}"

    [ -n "$user" ] && [ -n "$db" ] || return 0

    # Escape for SQL literal / identifier.
    pass_sql=$(printf '%s' "$pass" | sed "s/'/''/g")
    user_sql=$(printf '%s' "$user" | sed 's/"/""/g')
    db_sql=$(printf '%s' "$db" | sed 's/"/""/g')

    psql -v ON_ERROR_STOP=1 --no-password --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
SELECT 'CREATE ROLE "$user_sql" LOGIN PASSWORD ''$pass_sql'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$user_sql')\gexec
SELECT 'CREATE DATABASE "$db_sql" OWNER "$user_sql"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db_sql')\gexec
EOSQL
}

main

#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

usage() {
    cat <<'EOF'
Create and verify a PostgreSQL 17 volume from a running PostgreSQL 12 container.

The source container and volume are never stopped, modified, or removed. The
target volume must not already exist. Application writers must be stopped first.

Required environment variables:
  POSTGRES_SOURCE_CONTAINER   Running PostgreSQL 12 container name or ID
  POSTGRES_TARGET_VOLUME      New, unused Docker volume name
  POSTGRES_BACKUP_DIR         Absolute backup directory outside this repository
  POSTGRES_WRITES_STOPPED     Must be exactly YES

Optional environment variables:
  POSTGRES_TARGET_IMAGE       PostgreSQL 17 image (default: postgres:17)
  POSTGRES_TARGET_CONTAINER   Temporary restore container name
EOF
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

container_psql() {
    local container=$1
    local user=$2
    local database=$3
    local sql=$4
    docker exec "$container" psql \
        --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 \
        --username "$user" --dbname "$database" --command "$sql"
}

write_table_counts() {
    local container=$1
    local user=$2
    local database=$3
    local output_path=$4
    local schema
    local table
    local quoted_schema
    local quoted_table
    local count

    : >"$output_path"
    while IFS='|' read -r schema table; do
        [[ -n "$schema" && -n "$table" ]] || continue
        quoted_schema=${schema//\"/\"\"}
        quoted_table=${table//\"/\"\"}
        count=$(container_psql \
            "$container" "$user" "$database" \
            "SELECT count(*) FROM \"$quoted_schema\".\"$quoted_table\";")
        printf '%s.%s\t%s\n' "$schema" "$table" "$count" >>"$output_path"
    done < <(
        container_psql "$container" "$user" "$database" \
            "SELECT schemaname, tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY 1, 2;"
    )
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
    usage
    exit 0
fi
[[ $# -eq 0 ]] || fail "This command accepts configuration through environment variables only."

require_command docker
require_command sha256sum
require_command diff

source_container=${POSTGRES_SOURCE_CONTAINER:-}
target_volume=${POSTGRES_TARGET_VOLUME:-}
backup_dir=${POSTGRES_BACKUP_DIR:-}
target_image=${POSTGRES_TARGET_IMAGE:-postgres:17}
target_container=${POSTGRES_TARGET_CONTAINER:-parsetrail-postgres17-restore}

[[ -n "$source_container" ]] || fail "POSTGRES_SOURCE_CONTAINER is required."
[[ -n "$target_volume" ]] || fail "POSTGRES_TARGET_VOLUME is required."
[[ -n "$backup_dir" ]] || fail "POSTGRES_BACKUP_DIR is required."
[[ ${POSTGRES_WRITES_STOPPED:-} == "YES" ]] || fail \
    "Stop every application writer, then set POSTGRES_WRITES_STOPPED=YES."
[[ "$backup_dir" == /* ]] || fail "POSTGRES_BACKUP_DIR must be an absolute path."
[[ "$target_image" == postgres:17 || "$target_image" == postgres:17.* || "$target_image" == postgres@sha256:* ]] || fail \
    "POSTGRES_TARGET_IMAGE must identify PostgreSQL 17."
[[ "$source_container" != "$target_container" ]] || fail \
    "Source and temporary target container names must differ."

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/../.." && pwd -P)
mkdir -p -- "$backup_dir"
backup_dir=$(cd -- "$backup_dir" && pwd -P)
case "$backup_dir/" in
    "$repo_root/"*) fail "Store database backups outside the repository." ;;
esac

docker inspect --type container "$source_container" >/dev/null 2>&1 || fail \
    "Source container does not exist: $source_container"
[[ $(docker inspect --format '{{.State.Running}}' "$source_container") == "true" ]] || fail \
    "Source container is not running: $source_container"
if docker volume inspect "$target_volume" >/dev/null 2>&1; then
    fail "Target volume already exists; choose a new name: $target_volume"
fi
if docker inspect --type container "$target_container" >/dev/null 2>&1; then
    fail "Temporary target container already exists: $target_container"
fi

source_user=$(docker exec "$source_container" printenv POSTGRES_USER)
source_database=$(docker exec "$source_container" printenv POSTGRES_DB)
source_password=$(docker exec "$source_container" printenv POSTGRES_PASSWORD)
[[ -n "$source_user" && -n "$source_database" && -n "$source_password" ]] || fail \
    "Source container must expose POSTGRES_USER, POSTGRES_DB, and POSTGRES_PASSWORD."

source_version_num=$(container_psql \
    "$source_container" "$source_user" "$source_database" \
    "SHOW server_version_num;")
[[ "$source_version_num" == 12* ]] || fail \
    "Expected PostgreSQL 12 source; server_version_num is $source_version_num."

other_sessions=$(container_psql \
    "$source_container" "$source_user" "$source_database" \
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();")
[[ "$other_sessions" == "0" ]] || fail \
    "Source database still has $other_sessions other session(s); stop writers and retry."

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
dump_path="$backup_dir/parsetrail-postgres12-$timestamp.dump"
dump_partial="$dump_path.part"
source_counts="$backup_dir/parsetrail-postgres12-$timestamp.counts.tsv"
target_counts="$backup_dir/parsetrail-postgres17-$timestamp.counts.tsv"
cutover_env="$backup_dir/parsetrail-postgres17-$timestamp.cutover.env"

printf 'Recording source table counts...\n'
write_table_counts "$source_container" "$source_user" "$source_database" "$source_counts"

printf 'Creating consistent custom-format backup...\n'
docker exec "$source_container" pg_dump \
    --username "$source_user" --dbname "$source_database" \
    --format custom --compress 9 --no-owner --no-privileges >"$dump_partial"
[[ -s "$dump_partial" ]] || fail "pg_dump produced an empty backup."
mv -- "$dump_partial" "$dump_path"
sha256sum "$dump_path" >"$dump_path.sha256"

target_created=false
cleanup() {
    if [[ "$target_created" == "true" ]]; then
        docker rm --force "$target_container" >/dev/null 2>&1 || true
    fi
    rm -f -- "$dump_partial"
}
trap cleanup EXIT

printf 'Creating new PostgreSQL 17 target volume...\n'
docker volume create "$target_volume" >/dev/null
docker run --detach --name "$target_container" \
    --env POSTGRES_USER="$source_user" \
    --env POSTGRES_DB="$source_database" \
    --env POSTGRES_PASSWORD="$source_password" \
    --env PGDATA=/var/lib/postgresql/data/pgdata \
    --volume "$target_volume:/var/lib/postgresql/data" \
    "$target_image" >/dev/null
target_created=true

for _ in $(seq 1 60); do
    if docker exec "$target_container" pg_isready \
        --username "$source_user" --dbname "$source_database" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker exec "$target_container" pg_isready \
    --username "$source_user" --dbname "$source_database" >/dev/null 2>&1 || fail \
    "PostgreSQL 17 target did not become ready."

target_version_num=$(container_psql \
    "$target_container" "$source_user" "$source_database" \
    "SHOW server_version_num;")
[[ "$target_version_num" == 17* ]] || fail \
    "Expected PostgreSQL 17 target; server_version_num is $target_version_num."

printf 'Restoring backup into the new volume...\n'
docker exec --interactive "$target_container" pg_restore \
    --username "$source_user" --dbname "$source_database" \
    --exit-on-error --single-transaction --no-owner --no-privileges <"$dump_path"

printf 'Comparing every public table row count...\n'
write_table_counts "$target_container" "$source_user" "$source_database" "$target_counts"
diff --unified "$source_counts" "$target_counts"

cat >"$cutover_env" <<EOF
# Add these values to the deployment environment only after staging verification.
POSTGRES_IMAGE=$target_image
POSTGRES_VOLUME_NAME=$target_volume
EOF

printf '\nPostgreSQL 17 restore verified successfully.\n'
printf 'Backup: %s\n' "$dump_path"
printf 'Checksum: %s\n' "$dump_path.sha256"
printf 'Verified target volume: %s\n' "$target_volume"
printf 'Cutover values: %s\n' "$cutover_env"
printf 'The PostgreSQL 12 source container and volume were not modified.\n'

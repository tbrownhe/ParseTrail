#! /usr/bin/env bash

set -Eeuo pipefail
set -x

# Validate database connectivity. Schema changes happen only in migrate.sh.
python app/backend_pre_start.py

# Provision or validate the immutable statement-submission keyring. Rotation is
# an explicit maintenance command and is never triggered by application import.
python -m app.core.submission_keys provision

# Create initial data in DB
python app/initial_data.py

#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Provision or validate the immutable statement-submission keyring. Rotation is
# an explicit maintenance command and is never triggered by application import.
python -m app.core.submission_keys provision

# Create initial data in DB
python app/initial_data.py

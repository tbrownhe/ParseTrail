#! /usr/bin/env bash
set -e
set -x

python app/tests_pre_start.py
python -m app.tests.migrate_test_db

bash scripts/test.sh "$@"

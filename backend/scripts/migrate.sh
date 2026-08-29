#!/usr/bin/env bash

set -Eeuo pipefail
set -x

# Database migrations are an explicit deployment phase. They are intentionally
# absent from prestart.sh so replacing application services cannot migrate the
# schema as an unnoticed side effect.
python app/backend_pre_start.py
alembic upgrade head

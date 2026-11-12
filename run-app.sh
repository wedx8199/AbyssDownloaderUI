#!/bin/sh
# Resolve the app directory independently of the file manager's working directory.
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
PYTHON="$APP_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    printf '%s\n' "The app's Python environment is missing." "Follow the setup instructions in $APP_DIR/README.md first." >&2
    exit 1
fi

exec "$PYTHON" "$APP_DIR/app.py" "$@"

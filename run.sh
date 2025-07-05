#!/bin/sh

SCRIPT_DIR=$(dirname "$(realpath "$0")")

CONFIG_FILE="$SCRIPT_DIR/config.toml"
TEMPLATE_FILE="$SCRIPT_DIR/utils/.config.template.toml"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Copying config template..."
  cp "$TEMPLATE_FILE" "$CONFIG_FILE"
fi

docker run --rm -v $SCRIPT_DIR/out/:/app/assets -v $SCRIPT_DIR/.env:/app/.env -v $SCRIPT_DIR/config.toml:/app/config.toml -it rvmt

#!/usr/bin/env bash
set -Eeo pipefail
echo "Processing."
echo "Input:"
ls -al $MERCURE_IN_DIR

cp -r $MERCURE_IN_DIR/. $MERCURE_OUT_DIR
echo "Writing result.json..."
echo '{"foo":"bar", "__mercure_notification": {"text": "This is a mercure notification"}}' > "$MERCURE_OUT_DIR/result.json"

echo "Output:"
ls -al $MERCURE_OUT_DIR

echo "Processed."

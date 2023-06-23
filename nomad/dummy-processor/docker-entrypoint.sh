#!/usr/bin/env bash
set -Eeo pipefail
echo "Processing."
echo "Input:"
ls -al $MERCURE_IN_DIR

cp -r $MERCURE_IN_DIR/. $MERCURE_OUT_DIR

echo "Output:"
ls -al $MERCURE_OUT_DIR

echo '{"foo":"bar"}' > "$MERCURE_OUT_DIR/result.json"
echo "Processed."

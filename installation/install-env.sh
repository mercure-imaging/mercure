#!/bin/bash
set -euo pipefail

# Make defaults easily overridable
MERCURE_BASE=/opt/mercure

echo "Installing Python runtime environment..."
python3 -m venv "$MERCURE_BASE/env"

echo "Installing required Python packages..."
$MERCURE_BASE/env/bin/pip install wheel
$MERCURE_BASE/env/bin/pip install --isolated --quiet -r "$MERCURE_BASE/app/requirements.txt"

echo "Creating default configuration files..."
mkdir $MERCURE_BASE/config
cp $MERCURE_BASE/app/configuration/default_bookkeeper.env $MERCURE_BASE/config/bookkeeper.env
cp $MERCURE_BASE/app/configuration/default_mercure.json $MERCURE_BASE/config/mercure.json
cp $MERCURE_BASE/app/configuration/default_services.json $MERCURE_BASE/config/services.json
cp $MERCURE_BASE/app/configuration/default_webgui.env $MERCURE_BASE/config/webgui.env

# echo "Removing temporary files..."
# rm /tmp/miniconda.sh

echo "Done."
echo ""

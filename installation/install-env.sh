#!/bin/bash
set -euo pipefail

# Make defaults easily overrideable
MERCURE_BASE=/opt/mercure

echo "Installing Python runtime environment..."
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "/tmp/miniconda.sh"

bash /tmp/miniconda.sh -b -p /opt/miniconda
PATH="/opt/miniconda/bin:$PATH"
/opt/miniconda/bin/conda create -y -q --prefix "$MERCURE_BASE/env" python=3.6

echo "Installing required Python packages..."
$MERCURE_BASE/env/bin/pip install --quiet -r "$MERCURE_BASE/app/requirements.txt"

echo "Creating default configuration files..."
mkdir $MERCURE_BASE/config
cp $MERCURE_BASE/app/configuration/default_bookkeeper.env $MERCURE_BASE/config/bookkeeper.env
cp $MERCURE_BASE/app/configuration/default_mercure.json $MERCURE_BASE/config/mercure.json
cp $MERCURE_BASE/app/configuration/default_services.json $MERCURE_BASE/config/services.json
cp $MERCURE_BASE/app/configuration/default_webgui.env $MERCURE_BASE/config/webgui.env

echo "Removing temporary files..."
rm /tmp/miniconda.sh

echo "Done."
echo ""

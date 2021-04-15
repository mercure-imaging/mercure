#!/bin/bash
set -euo pipefail

# Make defaults easily overrideable
MERCUREBASE=$HOME

echo "Installing Python runtime environment..."
wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "$MERCUREBASE/miniconda.sh"
bash ~/miniconda.sh -b -p ~/miniconda
export PATH="$MERCUREBASE/miniconda/bin:$PATH"
conda create -y -q --prefix "$MERCUREBASE/mercure-env" python=3.6

echo "Installing required Python packages..."
$MERCUREBASE/mercure-env/bin/pip install --quiet -r "$MERCUREBASE/mercure/requirements.txt"

echo "Creating default configuration files..."
cp $MERCUREBASE/mercure/configuration/default_bookkeeper.env $MERCUREBASE/mercure/configuration/bookkeeper.env
cp $MERCUREBASE/mercure/configuration/default_mercure.json $MERCUREBASE/mercure/configuration/mercure.json
cp $MERCUREBASE/mercure/configuration/default_services.json $MERCUREBASE/mercure/configuration/services.json
cp $MERCUREBASE/mercure/configuration/default_webgui.env $MERCUREBASE/mercure/configuration/webgui.env

echo "Done. Please continue installation according to mercure user guide."
echo ""

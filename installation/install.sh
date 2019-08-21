#!/bin/bash
echo "Installing Python runtime environment..."
wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "$HOME/miniconda.sh"
bash ~/miniconda.sh -b -p ~/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
conda create -y -q --prefix "$HOME/hermes-env" python=3.6

echo "Installing required Python packages..."
$HOME/hermes-env/bin/pip install --quiet -r "$HOME/hermes/requirements.txt"

echo "Creating default configuration files..."
cp ../configuration/default_bookkeeper.env ../configuration/bookkeeper.env 
cp ../configuration/default_hermes.json ../configuration/hermes.json
cp ../configuration/default_services.json ../configuration/services.json
cp ../configuration/default_webgui.env ../configuration/webgui.env 

echo "Done. Please continue installation according to Hermes user guide."
echo ""

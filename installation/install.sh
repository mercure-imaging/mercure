#!/bin/bash
echo "Installing Python runtime environment..."
wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "$HOME/miniconda.sh"
bash ~/miniconda.sh -b -p ~/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
conda create -y -q --prefix "$HOME/mercure-env" python=3.6

echo "Installing required Python packages..."
$HOME/mercure-env/bin/pip install --quiet -r "$HOME/mercure/requirements.txt"

echo "Creating default configuration files..."
cp ../configuration/default_bookkeeper.env ../configuration/bookkeeper.env 
cp ../configuration/default_mercure.json ../configuration/mercure.json
cp ../configuration/default_services.json ../configuration/services.json
cp ../configuration/default_webgui.env ../configuration/webgui.env 

echo "Done. Please continue installation according to mercure user guide."
echo ""

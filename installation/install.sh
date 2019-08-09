#!/bin/bash
wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "$HOME/miniconda.sh"
bash ~/miniconda.sh -b -p ~/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
conda create -y -q --prefix "$HOME/hermes-env" python=3.6
$HOME/hermes-env/bin/pip install --quiet -r "$HOME/hermes/requirements.txt"
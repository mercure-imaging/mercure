#!/bin/bash
incoming=/home/hermes/hermes-data/incoming
binary=/home/hermes/hermes/bin/getdcmtags

echo "Starting DICOM receiver..."
storescp --fork --promiscuous -od "$incoming" +uf -xcr "$binary $incoming/#f 0.0.0.0:8080" 104

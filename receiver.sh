#!/bin/bash

## Startup script for Hermes' DICOM receive service
echo "Hermes DICOM receiver"
echo "---------------------"
echo ""

binary=bin/getdcmtags
config=./configuration/hermes.json

# Check if the configuration is accessible
if [ ! -f $config ]; then
    echo "ERROR: Unable to find configuration file"
    echo "ERROR: Terminating"
    exit 1    
fi

# Now read the needed values
port=$(cat $config | jq '.port')
incoming=$(cat $config | jq -r '.incoming_folder')
bookkeeper=$(cat $config | jq -r '.bookkeeper')

# Make sure that the port has been set (value could be missing or empty)
if [ $port = '""' ]
then
    port="null"
fi
if [ $port = "null" ]
then
    echo "ERROR: Port information is missing"
    echo "ERROR: Terminating"
    exit 1
fi
echo "Port: $port"

# Check if incoming folder exists
if [ ! -d "$incoming" ]; then
    echo "ERROR: Cannot access incoming folder"
    echo "ERROR: Terminating"
    exit 1
fi
echo "Incoming: $incoming"

# Check if the bookkeeper has been set
if [ -z "$bookkeeper" ]
then
    # If key is set to empty string, set as if key would be missing
    bookkeeper="null"
fi
if [ $bookkeeper = "null" ]
then
    # If bookkeeper is not configured, drop the argument in the binary call
    bookkeeper=""
else
    echo "Bookkeeper: $bookkeeper"
    # If configured, add prececing space so that both that two arguments are passed
    bookkeeper=" $bookkeeper"
fi

echo ""
echo "Starting receiver process..."
storescp --fork --promiscuous -od "$incoming" +uf -xcr "$binary $incoming/#f$bookkeeper" $port

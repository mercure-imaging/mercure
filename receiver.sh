#!/bin/bash

## Startup script for mercure's DICOM receive service
echo "mercure DICOM receiver"
echo "----------------------"
echo ""

binary=bin/getdcmtags

config_folder="${MERCURE_CONFIG_FOLDER:-/opt/mercure/config}"
config="${config_folder}/mercure.json"
echo "Configuration folder: ${config_folder}"
echo "Configuration file: ${config}"

# Check if the configuration is accessible
if [ ! -f $config ]; then
    echo "ERROR: Unable to find configuration file ${config}"
    echo "ERROR: Terminating"
    exit 1    
fi

# Now read the needed values
incoming=$(cat $config | jq -r '.incoming_folder')
port=$(cat $config | jq '.port')
bookkeeper=$(cat $config | jq -r '.bookkeeper')

# Check if incoming folder exists
if [ ! -d "$incoming" ]; then
    echo "ERROR: Cannot access incoming folder ${incoming}"
    echo "ERROR: Terminating"
    exit 1
fi
echo "Incoming: $incoming"

# Make sure that the port has been set (value could be missing or empty)
if [ $port = '""' ]
then
    port="null"
fi
if [ $port = "null" ]
then
    echo "Port information is missing. Using default value"
    port=104
fi
echo "Port: $port"

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
    # If configured, add preceding space so that both that two arguments are passed
    bookkeeper=" $bookkeeper"
fi

echo ""
echo "Starting receiver process on port $port, folder $incoming, bookeeper $bookkeeper"
storescp --fork --promiscuous -od "$incoming" +uf -xcr "$binary $incoming/#f$bookkeeper" $port

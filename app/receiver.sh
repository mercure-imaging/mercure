#!/bin/bash

## Startup script for mercure's DICOM receive service
echo "mercure DICOM receiver"
echo "----------------------"
echo ""
if [ $# -eq 0 ]; then
    echo "No arguments provided."
else
    echo "Arguments: $@"
fi
echo ""
binary=bin/getdcmtags

if [[ ! -f "$binary" ]] ; then
    if [[ $(lsb_release -rs) == "24.04" ]]; then 
        binary=bin/ubuntu24.04/getdcmtags
    elif [[ $(lsb_release -rs) == "22.04" ]]; then 
        binary=bin/ubuntu22.04/getdcmtags
    elif [[ $(lsb_release -rs) == "20.04" ]]; then 
        binary=bin/ubuntu20.04/getdcmtags
    elif [[ $(lsb_release -rs) == "18.04" ]]; then 
        binary=bin/ubuntu18.04/getdcmtags
    fi 
fi
if [[ -f "$binary" ]] ; then
    echo "getdcmtags binary at '$binary'"
else
    binary="$(dirname "$0")/$binary"
    if [[ -f "$binary" ]] ; then
        echo "getdcmtags binary at '$binary'"    
    else
        echo "ERROR: Unable to locate getdcmtags binary at '$binary'"
        echo "Terminating..."
        exit 1
    fi
fi

if $binary -h &> /dev/null; then
    echo "getdcmtags binary validated."
else 
    echo "ERROR: getdcmtags binary failed to start."
    echo "Terminating..."
    exit 1
fi
# Check if the configuration is accessible

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
incoming=$(jq -r '.incoming_folder' $config)
port=$(jq '.port' $config)
bookkeeper=$(jq -r '.bookkeeper' $config)
accept_compressed=$(jq -r '.accept_compressed_images' $config)
bookkeeper_api_key=$(jq -r '.bookkeeper_api_key' $config)
jq -r ".dicom_receiver.additional_tags // {} | keys_unsorted[]" $config > "./dcm_extra_tags" || (echo "Failed to parse and configure extra DICOM tags to read." && exit 1)

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
    port=11112
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
    bookkeeper_api_key=""
else
    echo "Bookkeeper: $bookkeeper"
    # If configured, add preceding space so that both that two arguments are passed
    bookkeeper=" $bookkeeper"
fi

transfer_syntax_option=""
if [ $accept_compressed = "true" ]
then
    echo "NOTE: Accepting all supported transfer syntaxes"
    transfer_syntax_option="+xa"
fi 

if [ $bookkeeper_api_key = "null" ]
then
    bookkeeper_api_key=""
else
    bookkeeper_api_key=" $bookkeeper_api_key"
fi

echo ""
echo "Starting receiver process on port $port, folder $incoming, bookkeeper $bookkeeper"

if [ "$MERCURE_TLS_ENABLED" -eq "1" ]
then
    echo "mercure has been configured for DICOM TLS. Starting in TLS mode."
    storescp +tls $MERCURE_TLS_KEY $MERCURE_TLS_CERT +cf $MERCURE_TLS_CA_CERT --fork --promiscuous $transfer_syntax_option -od "$incoming" +uf -xcr "$binary $incoming/#f #r #a #c$bookkeeper$bookkeeper_api_key $@" $port
else
    storescp --fork --promiscuous $transfer_syntax_option -od "$incoming" +uf -xcr "$binary $incoming/#f #r #a #c$bookkeeper$bookkeeper_api_key $@" $port
fi

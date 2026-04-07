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

# Locate getdcmtags binary
binary=bin/getdcmtags
if [[ ! -f "$binary" ]] ; then
    binary="$(dirname "$0")/$binary"
fi
if [[ -f "$binary" ]] ; then
    echo "getdcmtags binary at '$binary'"
else
    echo "ERROR: Unable to locate getdcmtags binary at '$binary'"
    echo "Terminating..."
    exit 1
fi

if $binary -h &> /dev/null; then
    echo "getdcmtags binary validated."
else
    echo "ERROR: getdcmtags binary failed to start."
    echo "Terminating..."
    exit 1
fi

# Locate storescp binary (bundled static build)
storescp_binary=bin/storescp
if [[ ! -f "$storescp_binary" ]] ; then
    storescp_binary="$(dirname "$0")/$storescp_binary"
fi
if [[ ! -f "$storescp_binary" ]] ; then
    echo "ERROR: Unable to locate storescp binary at '$storescp_binary'"
    echo "Terminating..."
    exit 1
fi
echo "storescp binary at '$storescp_binary'"

# Set DICOM dictionary path for statically-built storescp
dcmdict_dir="$(dirname "$storescp_binary")"
if [ -f "$dcmdict_dir/dicom.dic" ]; then
    export DCMDICTPATH="$dcmdict_dir/dicom.dic"
    echo "DCMDICTPATH set to $DCMDICTPATH"
fi

# Verify storescp version >= 3.7.0
storescp_version=$("$storescp_binary" --version 2>&1 | grep -oP 'v\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
if [ -z "$storescp_version" ]; then
    echo "ERROR: Unable to determine storescp version"
    echo "Terminating..."
    exit 1
fi
echo "storescp version: $storescp_version"

# Compare version: require >= 3.7.0
required_version="3.7.0"
if [ "$(printf '%s\n' "$required_version" "$storescp_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "ERROR: storescp version $storescp_version is below required $required_version"
    echo "Terminating..."
    exit 1
fi
echo "storescp version validated (>= $required_version)."

# Verify storescp was built from the required commit
required_commit="969c4b6c"
if [ -n "$required_commit" ]; then
    if ! "$storescp_binary" --version 2>&1 | grep -q "$required_commit"; then
        echo "ERROR: storescp binary was not built from required commit $required_commit"
        echo "Terminating..."
        exit 1
    fi
    echo "storescp commit validated ($required_commit)."
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

if [ $MERCURE_TLS_ENABLED ]
then
    echo "mercure has been configured for DICOM TLS. Starting in TLS mode."
    "$storescp_binary" +tls $MERCURE_TLS_KEY $MERCURE_TLS_CERT +cf $MERCURE_TLS_CA_CERT --fork --promiscuous $transfer_syntax_option -od "$incoming" +uf -xcr "$binary $incoming/#f #r #a #c$bookkeeper$bookkeeper_api_key $@" $port
else
    "$storescp_binary" --fork --promiscuous $transfer_syntax_option -od "$incoming" +uf -xcr "$binary $incoming/#f #r #a #c$bookkeeper$bookkeeper_api_key $@" $port
fi

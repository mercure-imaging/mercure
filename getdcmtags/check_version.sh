#!/usr/bin/env bash

binary_version=$(../bin/ubuntu22.04/getdcmtags --version | grep -oP 'Version \K.*' )
source_version=$(grep -oP '#define VERSION "\K.*(?=")' ../getdcmtags/main.cpp)

echo "Binary version: $binary_version"
echo "Source version: $source_version"
echo ""
if [ "$binary_version" == "$source_version" ]; then
    echo "Versions match."
    exit 0
else
    echo "Versions do not match!"
    exit 1
fi
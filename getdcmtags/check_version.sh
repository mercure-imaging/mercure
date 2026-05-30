#!/usr/bin/env bash

source_version=$(grep -oP '#define VERSION "getdcmtags Version \K.*(?=")' ../getdcmtags/main.cpp)
echo "Source version: $source_version"

binary_version=$(strings ../app/bin/getdcmtags | grep -oP "getdcmtags Version \K.*" )
echo "Binary version: $binary_version"

echo ""
if [ "$binary_version" != "$source_version" ]; then
    echo "Versions do not match!"
    exit 1
fi

echo "Versions match."

echo ""
echo "storescp binary:"
if [ -f ../app/bin/storescp ]; then
    ../app/bin/storescp --version 2>&1 | head -5
    echo "storescp binary OK"
else
    echo "ERROR: storescp binary not found"
    exit 1
fi

exit 0

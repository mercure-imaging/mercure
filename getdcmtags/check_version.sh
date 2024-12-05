#!/usr/bin/env bash

source_version=$(grep -oP '#define VERSION "getdcmtags Version \K.*(?=")' ../getdcmtags/main.cpp)
echo "Source version: $source_version"

binary_version_2004=$(strings ../app/bin/ubuntu20.04/getdcmtags | grep -oP "getdcmtags Version \K.*" )
echo "Binary version for Ubuntu 20.04: $binary_version_2004"

binary_version_2204=$(strings ../app/bin/ubuntu22.04/getdcmtags | grep -oP "getdcmtags Version \K.*" )
echo "Binary version for Ubuntu 22.04: $binary_version_2204"

binary_version_2404=$(strings ../app/bin/ubuntu24.04/getdcmtags | grep -oP "getdcmtags Version \K.*" )
echo "Binary version for Ubuntu 24.04: $binary_version_2404"

echo ""
if [ "$binary_version_2004" != "$source_version" ]; then
    echo "Versions do not match!"
    exit 1
fi
if [ "$binary_version_2204" != "$source_version" ]; then
    echo "Versions do not match!"
    exit 1
fi
if [ "$binary_version_2404" != "$source_version" ]; then
    echo "Versions do not match!"
    exit 1
fi

echo "All versions match."
exit 0

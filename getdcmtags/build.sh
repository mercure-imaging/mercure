#!/bin/bash
set -euo pipefail

build_docker_image() {
    local UBUNTU_VERSION=$1

    echo "Building Docker image for Ubuntu $UBUNTU_VERSION"

    # Build the Docker image
    docker build --build-arg UBUNTU_VERSION=$UBUNTU_VERSION -t mercure-getdcmtags-build:$UBUNTU_VERSION .

    if [ $? -ne 0 ]; then
        echo "Docker build failed for Ubuntu $UBUNTU_VERSION"
        return 1
    fi

    echo "Docker image for Ubuntu $UBUNTU_VERSION built successfully"
    echo "----------------------------------------"
}


build_qt_project() {
    local UBUNTU_VERSION=$1

    echo "Building for Ubuntu $UBUNTU_VERSION"

    docker run -it mercure-getdcmtags-build:$UBUNTU_VERSION
    local last_container=$(docker ps -lq)
    docker cp $last_container:/build/getdcmtags ../app/bin/ubuntu${UBUNTU_VERSION}/getdcmtags
    docker rm $last_container

    echo "Build for Ubuntu $UBUNTU_VERSION completed"
    echo "----------------------------------------"
}

# Main execution
echo "Starting getdcmtags build"
echo "======================================================="

# Build for each Ubuntu version
for VERSION in 20.04 22.04 24.04; do
    build_docker_image $VERSION
done

# Run builds and extract executables for each Ubuntu version
for VERSION in 20.04 22.04 24.04; do
    build_qt_project $VERSION
done



echo "All builds completed"
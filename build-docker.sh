#!/bin/bash
set -euo pipefail

#################################################################
# Create mercure from scratch in Docker environment
#################################################################
#
# Make sure to change the configuration below, as they are most
# likely different for your environment
#
# Once you are happy, simply run this script to build mercure
# See docker/docker-compose.yml for a sample script
#
#################################################################

#################################################################
# CONFIG SECTION
#################################################################
# Change prefix to your own Docker prefix if you want to make 
# your own custom build
PREFIX="mercureimaging"

# Read the version of the mercure source, which will be used for
# tagging the Docker images, unless a tag has been provided 
# through the environment variable MERCURE_TAG
if [ ! -f "VERSION" ]; then
    echo "Error: VERSION file missing. Unable to proceed."
    exit 1
fi
VERSION="dev" #`cat VERSION`
TAG=${MERCURE_TAG:-$VERSION}

# Define where mercure is going to store things
# You can redefine types of volumes in docker/docker-compose.yml
MERCUREBASE=/opt/mercure
DATADIR=$MERCUREBASE/data
CONFIGDIR=$MERCUREBASE/config
DBDIR=$MERCUREBASE/db
MERCURESRC=./

#################################################################
# BUILD SECTION
#################################################################
echo "Building Docker containers for mercure $VERSION"
echo "Using image tag $TAG"
echo ""

FORCE_BUILD="n"
while getopts ":y" opt; do
  case ${opt} in
    y )
      FORCE_BUILD="y"
      ;;
    \? )
      echo "Invalid Option: -$OPTARG" 1>&2
      exit 1
      ;;
    : )
      echo "Invalid Option: -$OPTARG requires an argument" 1>&2
      exit 1
      ;;
  esac
done

if [ $FORCE_BUILD = "y" ]; then
  echo "Forcing building"
else
  read -p "Proceed (y/n)? " ANS
  if [ "$ANS" = "y" ]; then
  echo ""
  else
  echo "Aborted."
  exit 0
  fi
fi

build_component () {
  docker build docker/$1 -t $PREFIX/mercure-$1:$TAG -t $PREFIX/mercure-$1:latest --build-arg VERSION_TAG=$TAG
}

docker build -t $PREFIX/mercure-base:$TAG -t $PREFIX/mercure-base:latest -f docker/base/Dockerfile .

for component in ui bookkeeper cleaner processor receiver router
do
  build_component $component
done

docker build nomad/sshd -t $PREFIX/alpine-sshd:latest
docker build nomad/processing -t $PREFIX/processing-step:$TAG -t $PREFIX/processing-step:latest
docker build nomad/dummy-processor -t $PREFIX/mercure-dummy-processor:$TAG -t $PREFIX/processing-step:latest

echo ""
echo "Done."
echo ""

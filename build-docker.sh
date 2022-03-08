#!/bin/bash
set -euo

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
VERSION=`cat VERSION`
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

docker build --no-cache -t $PREFIX/mercure-base:$TAG -t $PREFIX/mercure-base:latest -f docker/base/Dockerfile .
docker build docker/ui -t $PREFIX/mercure-ui:$TAG -t $PREFIX/mercure-ui:latest --build-arg VERSION_TAG=$TAG
docker build docker/bookkeeper -t $PREFIX/mercure-bookkeeper:$TAG -t $PREFIX/mercure-bookkeeper:latest --build-arg VERSION_TAG=$TAG
docker build docker/cleaner -t $PREFIX/mercure-cleaner:$TAG -t $PREFIX/mercure-cleaner:latest --build-arg VERSION_TAG=$TAG
docker build docker/dispatcher -t $PREFIX/mercure-dispatcher:$TAG -t $PREFIX/mercure-dispatcher:latest --build-arg VERSION_TAG=$TAG
docker build docker/processor -t $PREFIX/mercure-processor:$TAG -t $PREFIX/mercure-processor:latest --build-arg VERSION_TAG=$TAG
docker build docker/receiver -t $PREFIX/mercure-receiver:$TAG -t $PREFIX/mercure-receiver:latest --build-arg VERSION_TAG=$TAG
docker build docker/router -t $PREFIX/mercure-router:$TAG -t $PREFIX/mercure-router:latest --build-arg VERSION_TAG=$TAG
docker build nomad/sshd -t $PREFIX/alpine-sshd:latest
docker build nomad/processing -t $PREFIX/processing-step:$TAG -t $PREFIX/processing-step:latest
docker build nomad/dummy-processor -t $PREFIX/mercure-dummy-processor:$TAG -t $PREFIX/processing-step:latest

echo ""
echo "Done."
echo ""

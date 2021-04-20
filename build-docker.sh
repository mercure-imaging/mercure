#!/bin/bash
#################################################################
# Create Mercure from scratch in Docker environment
#################################################################
#
# Make sure to change the configuration below as they are most
# likely different for your environment
#
# Once you are happy, simply run this script to build mercure for you
# See docker/docker-compose.yml for a sample script
#
#################################################################
# CONFIG SECTION
#################################################################
# Change prefix to your own Docker prefix so you can make your own build
PREFIX=guruevi
SECRET='PutSomethingRandomHere'
DB_PWD='ChangePasswordHere'

# Where is mercure going to store things
# You can redefine types of volumes in docker/docker-compose.yml
MERCUREBASE=$HOME/mercure-docker
DATADIR=$MERCUREBASE/mercure-data
CONFIGDIR=$MERCUREBASE/mercure-config
DBDIR=$MERCUREBASE/mercure-db
MERCURESRC=./

#################################################################
# BUILD SECTION
#################################################################
docker build -t $PREFIX/mercure-base:latest -f docker/base/Dockerfile .
docker build docker/ui -t $PREFIX/mercure-ui:latest
docker build docker/bookkeeper -t $PREFIX/mercure-bookkeeper:latest
docker build docker/cleaner -t $PREFIX/mercure-cleaner:latest
docker build docker/dispatcher -t $PREFIX/mercure-dispatcher:latest
docker build docker/processor -t $PREFIX/mercure-processor:latest
docker build docker/receiver -t $PREFIX/mercure-receiver:latest
docker build docker/router -t $PREFIX/mercure-router:latest

#################################################################
# CONFIG MAKING SECTION
# TODO: Fully automated build?
#################################################################
if [ ! -f "$CONFIGDIR"/mercure.json ]; then
  # Generate the data folders
  mkdir -p "$DATADIR"
  mkdir "$DATADIR"/incoming "$DATADIR"/studies "$DATADIR"/outgoing "$DATADIR"/success
  mkdir "$DATADIR"/error "$DATADIR"/discard "$DATADIR"/processing
  mkdir -p "$CONFIGDIR"
  mkdir -p "$DBDIR"

  # Copy the sample configurations
  cp $MERCURESRC/configuration/default_bookkeeper.env "$CONFIGDIR"/bookkeeper.env
  cp $MERCURESRC/configuration/default_mercure.json "$CONFIGDIR"/mercure.json
  cp $MERCURESRC/configuration/default_services.json "$CONFIGDIR"/services.json
  cp $MERCURESRC/configuration/default_webgui.env "$CONFIGDIR"/webgui.env

  # Change the PostgreSQL and mercure bookkeeper string to match your build (check docker-compose.yml)
  sed -i '' -e "s/mercure:ChangePasswordHere@localhost/mercure:$DB_PWD@db/" "$CONFIGDIR"/bookkeeper.env
  sed -i '' -e "s/0.0.0.0:8080/bookkeeper:8080/" "$CONFIGDIR"/mercure.json
  sed -i '' -e "s/PutSomethingRandomHere/$SECRET/" "$CONFIGDIR"/webgui.env
fi
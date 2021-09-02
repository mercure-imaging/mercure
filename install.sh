#!/bin/bash
set -euo

SECRET="${MERCURE_SECRET:-unset}"
if [ "$SECRET" = "unset" ]
then 
  SECRET=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
fi

DB_PWD="${MERCURE_PASSWORD:-unset}"
if [ "$DB_PWD" = "unset" ]
then 
  DB_PWD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
fi

MERCURE_BASE=/opt/mercure
DATA_PATH=$MERCURE_BASE/data
CONFIG_PATH=$MERCURE_BASE/config
DB_PATH=$MERCURE_BASE/db
MERCURE_SRC=.

if [[ ! -e $MERCURE_BASE ]]; then
    echo "Creating $MERCURE_BASE"
    sudo mkdir -p $MERCURE_BASE
    sudo chown $USER:$USER $MERCURE_BASE
fi

if [[ ! -e $DATA_PATH ]]; then
    echo "Creating $DATA_PATH"
    sudo mkdir "$DATA_PATH"
    sudo mkdir "$DATA_PATH"/incoming "$DATA_PATH"/studies "$DATA_PATH"/outgoing "$DATA_PATH"/success
    sudo mkdir "$DATA_PATH"/error "$DATA_PATH"/discard "$DATA_PATH"/processing
    sudo chown -R $USER:$USER $DATA_PATH
fi

if [[ ! -e $CONFIG_PATH ]]; then
    echo "Creating $CONFIG_PATH"
    sudo mkdir $CONFIG_PATH
    sudo chown $USER:$USER $CONFIG_PATH
fi

if [[ ! -e $DB_PATH ]]; then
    echo "Creating $DB_PATH"
    sudo mkdir $DB_PATH
    sudo chown $USER:$USER $DB_PATH
fi

if [ ! -f "$CONFIG_PATH"/mercure.json ]; then
  echo "Copying configuration files"
  cp $MERCURE_SRC/configuration/default_bookkeeper.env "$CONFIG_PATH"/bookkeeper.env
  cp $MERCURE_SRC/configuration/default_mercure.json "$CONFIG_PATH"/mercure.json
  cp $MERCURE_SRC/configuration/default_services.json "$CONFIG_PATH"/services.json
  cp $MERCURE_SRC/configuration/default_webgui.env "$CONFIG_PATH"/webgui.env
  echo "POSTGRES_PASSWORD=$DB_PWD" > "$CONFIG_PATH"/db.env

  # Change the PostgreSQL and mercure bookkeeper string to match your build (check docker-compose.yml)
  sed -i -e "s/mercure:ChangePasswordHere@localhost/mercure:$DB_PWD@db/" "$CONFIG_PATH"/bookkeeper.env
  sed -i -e "s/0.0.0.0:8080/bookkeeper:8080/" "$CONFIG_PATH"/mercure.json
  sed -i -e "s/PutSomethingRandomHere/$SECRET/" "$CONFIG_PATH"/webgui.env
fi

if [ ! -f "$MERCURE_BASE"/docker-compose.yml ]; then
  cp $MERCURE_SRC/docker/docker-compose.yml $MERCURE_BASE
  sudo chown $USER:$USER "$MERCURE_BASE"/docker-compose.yml
fi

if [ ! -f "$MERCURE_BASE"/docker-compose.override.yml ]; then
  cp $MERCURE_SRC/docker/docker-compose.override.yml $MERCURE_BASE
  sudo chown $USER:$USER "$MERCURE_BASE"/docker-compose.override.yml
  sed -i -e "s;MERCURE_SRC;$(readlink -f $MERCURE_SRC);" "$MERCURE_BASE"/docker-compose.override.yml
fi
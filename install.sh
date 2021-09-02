#!/bin/bash
set -euo pipefail

error() {
  local parent_lineno="$1"
  local code="${3:-1}"
  echo "Error on or near line ${parent_lineno}"
  exit "${code}"
}
trap 'error ${LINENO}' ERR

OWNER=$USER
if [ $OWNER = "root" ]
then
  OWNER=$(logname)
  echo "Running as root, but setting $OWNER as owner."
fi

SECRET="${MERCURE_SECRET:-unset}"
if [ "$SECRET" = "unset" ]
then 
  SECRET=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)
fi

DB_PWD="${MERCURE_PASSWORD:-unset}"
if [ "$DB_PWD" = "unset" ]
then 
  DB_PWD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)
fi

MERCURE_BASE=/opt/mercure
DATA_PATH=$MERCURE_BASE/data
CONFIG_PATH=$MERCURE_BASE/config
DB_PATH=$MERCURE_BASE/db
MERCURE_SRC=.

if [[ ! -e $MERCURE_BASE ]]; then
    echo "Creating $MERCURE_BASE..."
    sudo mkdir -p $MERCURE_BASE
    sudo chown $OWNER:$OWNER $MERCURE_BASE
fi

if [[ ! -e $DATA_PATH ]]; then
    echo "Creating $DATA_PATH..."
    sudo mkdir "$DATA_PATH"
    sudo mkdir "$DATA_PATH"/incoming "$DATA_PATH"/studies "$DATA_PATH"/outgoing "$DATA_PATH"/success
    sudo mkdir "$DATA_PATH"/error "$DATA_PATH"/discard "$DATA_PATH"/processing
    sudo chown -R $OWNER:$OWNER $DATA_PATH
fi

if [[ ! -e $CONFIG_PATH ]]; then
    echo "Creating $CONFIG_PATH..."
    sudo mkdir $CONFIG_PATH
    sudo chown $OWNER:$OWNER $CONFIG_PATH
fi

if [[ ! -e $DB_PATH ]]; then
    echo "Creating $DB_PATH..."
    sudo mkdir $DB_PATH
    sudo chown $OWNER:$OWNER $DB_PATH
fi

if [ ! -f "$CONFIG_PATH"/mercure.json ]; then
  echo "Copying configuration files..."
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
  echo "Copying docker-compose.yml..."
  cp $MERCURE_SRC/docker/docker-compose.yml $MERCURE_BASE
  sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.yml
fi

if [ ! -f "$MERCURE_BASE"/docker-compose.override.yml ]; then
  echo "Copying docker-compose.override.yml..."
  cp $MERCURE_SRC/docker/docker-compose.override.yml $MERCURE_BASE
  sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.override.yml
  sed -i -e "s;MERCURE_SRC;$(readlink -f $MERCURE_SRC);" "$MERCURE_BASE"/docker-compose.override.yml
fi

echo "Installation complete"
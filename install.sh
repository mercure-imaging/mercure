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

if [ -f "$CONFIG_PATH"/db.env ]; then 
  sudo chown $USER "$CONFIG_PATH"/db.env 
  source "$CONFIG_PATH"/db.env # Don't accidentally generate a new database password
  sudo chown $OWNER "$CONFIG_PATH"/db.env 
  DB_PWD=$POSTGRES_PASSWORD
fi

echo "Mercure installation folder: $MERCURE_BASE"
echo "Data folder: $DATA_PATH"
echo "Config folder: $CONFIG_PATH"
echo "Database folder: $DB_PATH"
echo "Mercure source directory: $(readlink -f $MERCURE_SRC)"


create_user () {
  id -u mercure &>/dev/null || sudo useradd -ms /bin/bash mercure
  OWNER=mercure
}

create_folder () {
  if [[ ! -e $1 ]]; then
    echo "## Creating $1"
    sudo mkdir -p $1
    sudo chown $OWNER:$OWNER $1
    sudo chmod a+x $1
  else
    echo "## $1 already exists."
  fi
}
create_folders () {
  create_folder $MERCURE_BASE
  create_folder $CONFIG_PATH
  if [ $INSTALL_TYPE = "docker" ]; then
    create_folder $DB_PATH
  fi

  if [[ ! -e $DATA_PATH ]]; then
      echo "## Creating $DATA_PATH..."
      sudo mkdir "$DATA_PATH"
      sudo mkdir "$DATA_PATH"/incoming "$DATA_PATH"/studies "$DATA_PATH"/outgoing "$DATA_PATH"/success
      sudo mkdir "$DATA_PATH"/error "$DATA_PATH"/discard "$DATA_PATH"/processing
      sudo chown -R $OWNER:$OWNER $DATA_PATH
      sudo chmod a+x $DATA_PATH
  else
    echo "## $DATA_PATH already exists."
  fi
}

install_configuration () {
  if [ ! -f "$CONFIG_PATH"/mercure.json ]; then
    echo "## Copying configuration files..."
    sudo chown $USER "$CONFIG_PATH" 
    cp "$MERCURE_SRC"/configuration/default_bookkeeper.env "$CONFIG_PATH"/bookkeeper.env
    cp "$MERCURE_SRC"/configuration/default_mercure.json "$CONFIG_PATH"/mercure.json
    cp "$MERCURE_SRC"/configuration/default_services.json "$CONFIG_PATH"/services.json
    cp "$MERCURE_SRC"/configuration/default_webgui.env "$CONFIG_PATH"/webgui.env
    echo "POSTGRES_PASSWORD=$DB_PWD" > "$CONFIG_PATH"/db.env

    if [ $INSTALL_TYPE = "systemd" ]; then 
      sed -i -e "s/mercure:ChangePasswordHere@localhost/mercure:$DB_PWD@localhost/" "$CONFIG_PATH"/bookkeeper.env
    elif [ $INSTALL_TYPE = "docker" ]; then
      sed -i -e "s/mercure:ChangePasswordHere@localhost/mercure:$DB_PWD@db/" "$CONFIG_PATH"/bookkeeper.env
      sed -i -e "s/0.0.0.0:8080/bookkeeper:8080/" "$CONFIG_PATH"/mercure.json
    fi
    sed -i -e "s/PutSomethingRandomHere/$SECRET/" "$CONFIG_PATH"/webgui.env
    sudo chown -R $OWNER:$OWNER "$CONFIG_PATH"
    sudo chmod -R o-r "$CONFIG_PATH"
    sudo chmod a+xr "$CONFIG_PATH"
  fi
}

install_docker () {
  echo "## Installing Docker..."
  sudo apt-get update
  sudo apt-get remove docker docker-engine docker.io || true
  echo '* libraries/restart-without-asking boolean true' | sudo debconf-set-selections
  sudo apt-get install apt-transport-https ca-certificates curl software-properties-common -y
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg |  sudo apt-key add -
  sudo apt-key fingerprint 0EBFCD88
  sudo add-apt-repository \
      "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) \
      stable"
  sudo apt-get update
  sudo apt-get install -y docker-ce
  # Restart docker to make sure we get the latest version of the daemon if there is an upgrade
  sudo service docker restart
  # Make sure we can actually use docker as the vagrant user
  sudo usermod -a -G docker $OWNER
  sudo docker --version

  echo "## Installing Docker-Compose..."
  sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
  sudo docker-compose --version
}

setup_docker () {
  if [ ! -f "$MERCURE_BASE"/docker-compose.yml ]; then
    echo "## Copying docker-compose.yml..."
    cp $MERCURE_SRC/docker/docker-compose.yml $MERCURE_BASE
    sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.yml
  fi
}

setup_docker_dev () {
  if [ ! -f "$MERCURE_BASE"/docker-compose.override.yml ]; then
    echo "## Copying docker-compose.override.yml..."
    cp $MERCURE_SRC/docker/docker-compose.override.yml $MERCURE_BASE
    sed -i -e "s;MERCURE_SRC;$(readlink -f $MERCURE_SRC);" "$MERCURE_BASE"/docker-compose.override.yml
    sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.override.yml
  fi
}

build_docker () {
  echo "## Building mercure docker containers..."  
  sudo $MERCURE_SRC/build-docker.sh
}

start_docker () {
  echo "## Starting docker compose..."  
  cd /opt/mercure
  GID=$(getent group docker | cut -d: -f3) docker-compose up -d
}

install_app_files() {
  if [ ! -e "$MERCURE_BASE"/app ]; then
    echo "## Installing app files..."
    sudo mkdir "$MERCURE_BASE"/app
    sudo find "$MERCURE_SRC" -not -path \*/.\* -type d -exec mkdir -p -- "$MERCURE_BASE"/app/{} \;
    sudo find "$MERCURE_SRC" -not -path \*/.\* -type f -exec cp -- {} "$MERCURE_BASE"/app/{} \;
 
    if [[ $(lsb_release -rs) == "20.04" ]]; then 
      sudo cp $MERCURE_SRC/bin/ubuntu20.04/getdcmtags "$MERCURE_BASE"/app/bin/getdcmtags
    fi 
 
    sudo chown -R $OWNER:$OWNER "$MERCURE_BASE/app"
  fi
}

install_packages() {
  echo "## Installing Linux packages..."
  sudo apt-get update
  sudo apt-get install -y build-essential wget git dcmtk jq inetutils-ping sshpass postgresql postgresql-contrib
}

install_conda() {
  if [ ! -x "$(command -v conda)" ]; then # Can't find conda in PATH
    echo "## Installing Miniconda..."
    if [ ! -e "/opt/miniconda" ]; then
      wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "/tmp/miniconda.sh"
      sudo bash /tmp/miniconda.sh -b -p /opt/miniconda
    fi
    PATH="/opt/miniconda/bin:$PATH"
  fi
}

install_dependencies() {
  install_conda
  echo "## Installing Python runtime environment..."
  if [ ! -e "$MERCURE_BASE/env" ]; then
    sudo mkdir "$MERCURE_BASE/env" && sudo chown $USER "$MERCURE_BASE/env"
    sudo /opt/miniconda/bin/conda create -y -q --prefix "$MERCURE_BASE/env" python=3.6
    echo "## Installing required Python packages..."
    sudo $MERCURE_BASE/env/bin/pip install --quiet -r "$MERCURE_BASE/app/requirements.txt"
    sudo chown -R $OWNER:$OWNER "$MERCURE_BASE/env"
  fi
}

install_postgres() {
  echo "## Setting up postgres..."
  sudo -u postgres -s <<- EOM
    createuser mercure
    createdb mercure -O mercure
    psql -c "ALTER USER mercure WITH PASSWORD '$DB_PWD';"
EOM
}

install_services() {
  echo "## Installing services..."
  sudo cp "$MERCURE_SRC"/installation/*.service /etc/systemd/system
  sudo systemctl enable mercure_bookkeeper.service mercure_cleaner.service mercure_dispatcher.service mercure_receiver.service mercure_router.service mercure_ui.service mercure_processor.service
  sudo systemctl start mercure_bookkeeper.service mercure_cleaner.service mercure_dispatcher.service mercure_receiver.service mercure_router.service mercure_ui.service mercure_processor.service
}

systemd_install () {
  echo "## Performing systemd-type mercure installation..."
  create_user
  create_folders
  install_configuration
  sudo cp "$MERCURE_SRC"/installation/mercure-sudoer /etc/sudoers.d/mercure
  install_packages
  install_docker
  install_app_files
  install_dependencies
  install_postgres
  sudo chown -R mercure:mercure "$MERCURE_BASE"
  install_services
}

docker_install () {
  echo "## Performing docker-type mercure installation..."
  create_folders
  install_configuration
  install_docker
  build_docker
  setup_docker
  #setup_docker_dev
  start_docker
}

INSTALL_TYPE="${1:-docker}"
FORCE_INSTALL="${2:-n}"

if [ $FORCE_INSTALL = "y" ]; then
  echo "Forcing installation"
else
  read -p "Install with $INSTALL_TYPE (y/n)? " ANS
  if [ "$ANS" = "y" ]; then
    echo "Installing"
  else
    echo "Not installing"
    exit 0
  fi
fi

if [ $INSTALL_TYPE = "systemd" ]; then 
  systemd_install
elif [ $INSTALL_TYPE = "docker" ]; then
  docker_install
else
  echo "Error: Invalid option $INSTALL_TYPE"
  exit 0
fi

echo "Installation complete"

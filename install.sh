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
  if [ $INSTALL_TYPE != "systemd" ]; then
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

install_nomad () {
  echo "Installing Nomad..."
  NOMAD_VERSION=1.2.0
  if [ ! -x "$(command -v unzip)" ]; then 
    sudo apt-get install -y unzip
  fi 

  if [ ! -x "$(command -v nomad)" ]; then 
    curl -sSL https://releases.hashicorp.com/nomad/${NOMAD_VERSION}/nomad_${NOMAD_VERSION}_linux_amd64.zip -o /tmp/nomad.zip
    unzip -o /tmp/nomad.zip  -d /tmp 
    sudo install /tmp/nomad /usr/bin/nomad
    nomad -autocomplete-install
  fi 
  if [ ! -d /etc/nomad.d ]; then
    sudo mkdir -p /etc/nomad.d
    sudo chmod a+w /etc/nomad.d
  fi

  if [ ! -f "/etc/systemd/system/nomad.service" ]; then 
      (
    cat <<-EOFB
    [Unit]
    Description=nomad
    Requires=network-online.target
    After=network-online.target
    [Service]
    Restart=on-failure
    ExecStart=/usr/bin/nomad agent -bind 0.0.0.0 -log-level INFO -config /etc/nomad.d/
    ExecReload=/bin/kill -HUP \$MAINPID
    [Install]
    WantedBy=multi-user.target
EOFB
    ) | sudo tee /etc/systemd/system/nomad.service
    sudo systemctl enable nomad.service
    sudo systemctl restart nomad.service
  fi

  if [ ! -x "$(command -v consul)" ]; then 
    echo "Installing Consul..."
    CONSUL_VERSION=1.9.0
    curl -sSL https://releases.hashicorp.com/consul/${CONSUL_VERSION}/consul_${CONSUL_VERSION}_linux_amd64.zip -o /tmp/consul.zip
    unzip -o /tmp/consul.zip -d /tmp
    sudo install /tmp/consul /usr/bin/consul
  fi
  if [ ! -f "/etc/systemd/system/consul.service" ]; then 
    (
    cat <<-EOFA
      [Unit]
      Description=consul agent
      Requires=network-online.target
      After=network-online.target

      [Service]
      Restart=on-failure
      ExecStart=/usr/bin/consul agent -dev
      ExecReload=/bin/kill -HUP \$MAINPID

      [Install]
      WantedBy=multi-user.target
EOFA
    ) | sudo tee /etc/systemd/system/consul.service
    sudo systemctl enable consul.service
    sudo systemctl restart consul
  fi
  sudo systemctl daemon-reload

  for bin in cfssl cfssl-certinfo cfssljson
  do
    if [ ! -x "$(command -v $bin)" ]; then 
      echo "Installing $bin..."
      curl -sSL https://pkg.cfssl.org/R1.2/${bin}_linux-amd64 -o /tmp/${bin}
      sudo install /tmp/${bin} /usr/local/bin/${bin}
    fi
  done

  if [ ! -d /opt/cni/bin ]; then 
    curl -L -o /tmp/cni-plugins.tgz https://github.com/containernetworking/plugins/releases/download/v0.9.1/cni-plugins-linux-amd64-v0.9.1.tgz
    sudo mkdir -p /opt/cni/bin
    sudo tar -C /opt/cni/bin -xzf /tmp/cni-plugins.tgz
  fi
}

setup_nomad_keys() {
  if [ ! -f "$MERCURE_BASE"/processor-keys/id_rsa ]; then
    sudo mkdir /opt/mercure/processor-keys/
    echo "Generating SSH key..."
    sudo ssh-keygen -t rsa -N '' -f /opt/mercure/processor-keys/id_rsa
    sudo chown -R $OWNER:$OWNER "$MERCURE_BASE/processor-keys"
  fi
}

setup_nomad() {
  setup_nomad_keys

  if [ ! -f "$MERCURE_BASE"/mercure.nomad ]; then
    echo "## Copying mercure.nomad..."
    sudo cp $MERCURE_SRC/nomad/mercure.nomad $MERCURE_BASE
    sudo sed -i "s#SSHPUBKEY#$(cat /opt/mercure/processor-keys/id_rsa.pub)#g"  $MERCURE_BASE/mercure.nomad
    sudo cp $MERCURE_SRC/nomad/mercure-processor.nomad $MERCURE_BASE
    sudo cp $MERCURE_SRC/nomad/mercure-ui.nomad $MERCURE_BASE
    sudo cp $MERCURE_SRC/nomad/policies/anonymous-strict.policy.hcl $MERCURE_BASE

    if [ ! -d $MERCURE_BASE/db ]; then
      sudo mkdir $MERCURE_BASE/db
    fi
    sudo chown $OWNER:$OWNER "$MERCURE_BASE"/*
  fi
  sudo cp $MERCURE_SRC/nomad/server.hcl /etc/nomad.d
  sudo cp $MERCURE_SRC/nomad/client.hcl /etc/nomad.d

  sudo systemctl start nomad
  echo "Waiting for Nomad to start..."
  until [[ $(curl -q http://localhost:4646) ]];
  do
    echo -n "."
    sleep 1s;
  done;

  if [ -z "${NOMAD_TOKEN:-}" ]; then 
    if [ ! -x "$(command -v jq)" ]; then 
      sudo apt-get install -y jq
    fi
    echo "NOMAD_TOKEN not set. Attempting to bootstrap Nomad ACL."
    BOOTSTRAP_RESULT="$(nomad acl bootstrap -json || echo failed )"
    if [[ "$BOOTSTRAP_RESULT" = "failed" ]]; then 
      echo "Warning: NOMAD_TOKEN is unset, and bootstrapping the ACL failed. Registering the jobs will likely fail."
    else
      new_secret_id="$(echo $BOOTSTRAP_RESULT | jq -r .SecretID)"
      new_accessor_id="$(echo $BOOTSTRAP_RESULT | jq -r .AccessorID)"
      echo NOMAD_TOKEN=$new_secret_id
      export NOMAD_TOKEN=$new_secret_id
    fi
  fi
  nomad acl policy apply -description "Mercure anonymous policy" anonymous $MERCURE_BASE/anonymous-strict.policy.hcl 
  nomad run -detach $MERCURE_BASE/mercure.nomad
  nomad run -detach $MERCURE_BASE/mercure-ui.nomad
  nomad run -detach $MERCURE_BASE/mercure-processor.nomad

  if [ ! -z "${BOOTSTRAP_RESULT:-}" ]; then
    echo "Nomad ACL has been bootstrapped. Your managment key information follows. Keep this safe!"
    echo $BOOTSTRAP_RESULT | jq
  fi
}

install_docker () {
  if [ ! -x "$(command -v docker)" ]; then 
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
  fi

  if [ ! -x "$(command -v docker-compose)" ]; then 
    echo "## Installing Docker-Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    sudo docker-compose --version
  fi
}

setup_docker () {
  if [ ! -f "$MERCURE_BASE"/docker-compose.yml ]; then
    echo "## Copying docker-compose.yml..."
    sudo cp $MERCURE_SRC/docker/docker-compose.yml $MERCURE_BASE
    sudo sed -i -e "s/\\\${GID}/$(getent group docker | cut -d: -f3)/g" $MERCURE_BASE/docker-compose.yml
    sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.yml
  fi
}

setup_docker_dev () {
  if [ ! -f "$MERCURE_BASE"/docker-compose.override.yml ]; then
    echo "## Copying docker-compose.override.yml..."
    sudo cp $MERCURE_SRC/docker/docker-compose.override.yml $MERCURE_BASE
    sudo sed -i -e "s;MERCURE_SRC;$(readlink -f $MERCURE_SRC);" "$MERCURE_BASE"/docker-compose.override.yml
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
  sudo docker-compose up -d
}

install_app_files() {
  if [ ! -e "$MERCURE_BASE"/app ]; then
    echo "## Installing app files..."
    sudo mkdir "$MERCURE_BASE"/app
    sudo cp -R "$MERCURE_SRC" "$MERCURE_BASE"/app
    sudo chown -R $OWNER:$OWNER "$MERCURE_BASE/app"
  fi
}

install_packages() {
  echo "## Installing Linux packages..."
  sudo apt-get update
  sudo apt-get install -y build-essential wget git dcmtk jq inetutils-ping sshpass postgresql postgresql-contrib libpq-dev
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
  if [ $DOCKER_BUILD = true ]; then
    build_docker
  fi
  setup_docker
  if [ $DOCKER_DEV = true ]; then
    setup_docker_dev
  fi
  start_docker
}

nomad_install () {
  create_folders
  install_app_files
  install_configuration
  install_docker
  install_nomad
  setup_nomad
}

FORCE_INSTALL="n"

while getopts ":hy" opt; do
  case ${opt} in
    h )
      echo "Usage:"
      echo "    install.sh -h                     Display this help message."
      echo "    install.sh [-y] docker [OPTIONS]  Install with docker-compose."
      echo "    install.sh [-y] systemd           Install as systemd service."
      echo "    install.sh [-y] nomad             Install as nomad job."

      echo "    Options:   "
      echo "              docker:"
      echo "                      -d              Development mode "
      echo "                      -b              Build containers"
      exit 0
      ;;
    y )
      FORCE_INSTALL="y"
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
shift $((OPTIND -1))
OPTIND=1
INSTALL_TYPE="${1:-docker}"
if [[ $# > 0 ]];  then shift; fi

if [ $INSTALL_TYPE = "docker" ]; then
  DOCKER_DEV=false
  DOCKER_BUILD=false
  while getopts ":db" opt; do
    case ${opt} in
      d )
        DOCKER_DEV=true
        ;;
      b )
        DOCKER_BUILD=true
        ;;
      \? )
        echo "Invalid Option for \"docker\": -$OPTARG" 1>&2
        exit 1
        ;;
    esac
  done
  shift $((OPTIND -1))
fi

if [ $FORCE_INSTALL = "y" ]; then
  echo "Forcing installation"
else
  read -p "Install with $INSTALL_TYPE (y/n)? " ANS
  if [ "$ANS" = "y" ]; then
    echo "Installing Mercure."
  else
    echo "Installation aborted."
    exit 0
  fi
fi

case "$INSTALL_TYPE" in 
  systemd )
    systemd_install
    ;;
  docker )
    docker_install
    ;;
  nomad ) 
    nomad_install
    ;;
  * )
    echo "Error: unrecognized option $INSTALL_TYPE"
    exit 1
    ;;
esac

echo "Installation complete"

#!/bin/bash
set -euo pipefail

error() {
  local parent_lineno="$1"
  local code="${3:-1}"
  echo "Error on or near line ${parent_lineno}"
  exit "${code}"
}
trap 'error ${LINENO}' ERR

UBUNTU_VERSION=$(lsb_release -rs)
if [ $UBUNTU_VERSION != "20.04" ] && [ $UBUNTU_VERSION != "22.04" ] && [ $UBUNTU_VERSION != "24.04" ]; then
  echo "Invalid operating system!"
  echo "This mercure version requires Ubuntu 20.04 LTS, 22.04 LTS, or Ubuntu 24.04 LTS"
  echo "Detected operating system = $UBUNTU_VERSION"
  exit 1
fi

if [ ! -f "app/VERSION" ]; then
    echo "Error: VERSION file missing. Unable to proceed."
    exit 1
fi
VERSION=`cat app/VERSION`
IMAGE_TAG=":${MERCURE_TAG:-$VERSION}"
VER_LENGTH=${#VERSION}+28
echo ""
echo "mercure Installer - Version $VERSION"
for ((i=1;i<=VER_LENGTH;i++)); do
    echo -n "="
done
echo ""
echo ""
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

BOOKKEEPER_SECRET=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)

DB_PWD="${MERCURE_PASSWORD:-unset}"
if [ "$DB_PWD" = "unset" ]
then
  DB_PWD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)
fi
MERCURE_BASE=/opt/mercure
DATA_PATH=$MERCURE_BASE/data
CONFIG_PATH=$MERCURE_BASE/config
DB_PATH=$MERCURE_BASE/db
MERCURE_SRC=$(readlink -f .)

if [ -f "$CONFIG_PATH"/db.env ]; then 
  sudo chown $USER "$CONFIG_PATH"/db.env 
  source "$CONFIG_PATH"/db.env # Don't accidentally generate a new database password
  sudo chown $OWNER "$CONFIG_PATH"/db.env 
  DB_PWD=$POSTGRES_PASSWORD
fi

echo "Installation folder:  $MERCURE_BASE"
echo "Data folder:          $DATA_PATH"
echo "Config folder:        $CONFIG_PATH"
echo "Database folder:      $DB_PATH"
echo "Source folder:        $MERCURE_SRC"
echo ""

create_user () {
  id -u mercure &>/dev/null || sudo useradd -ms /bin/bash mercure
  OWNER=mercure
}


create_folder () {
    for folder in "$@"; do
        if [[ ! -e "$folder" ]]; then
            echo "## Creating $folder"
            sudo mkdir -p "$folder"
            sudo chown "$OWNER:$OWNER" "$folder"
            sudo chmod a+x "$folder"
        else
            echo "## $folder already exists."
        fi
    done
}

create_folders () {
  create_folder $MERCURE_BASE $CONFIG_PATH
  if [ $INSTALL_TYPE != "systemd" ] && [ $INSTALL_TYPE != "systemd-sso" ]; then
    create_folder $DB_PATH
  fi

  if [[ ! -e $DATA_PATH ]]; then
      echo "## Creating $DATA_PATH..."
      create_folder "$DATA_PATH"
      local paths=("incoming" "studies" "outgoing" "success" "error" "discard" "jobs" "processing")
      for path in "${paths[@]}"; do
        create_folder "$DATA_PATH"/$path
      done
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
    cp "$MERCURE_SRC"/configuration/default_receiver.env "$CONFIG_PATH"/receiver.env
    cp "$MERCURE_SRC"/configuration/default_mercure.json "$CONFIG_PATH"/mercure.json
    cp "$MERCURE_SRC"/configuration/default_services.json "$CONFIG_PATH"/services.json
    cp "$MERCURE_SRC"/configuration/default_webgui.env "$CONFIG_PATH"/webgui.env
    echo "POSTGRES_PASSWORD=$DB_PWD" > "$CONFIG_PATH"/db.env

    if [ $INSTALL_TYPE = "systemd" ] || [ $INSTALL_TYPE = "systemd-sso" ]; then 
      sed -i -e "s/mercure:ChangePasswordHere@localhost/mercure:$DB_PWD@localhost/" "$CONFIG_PATH"/bookkeeper.env
    elif [ $INSTALL_TYPE = "docker" ]; then
      sed -i -e "s/mercure:ChangePasswordHere@localhost/mercure:$DB_PWD@db/" "$CONFIG_PATH"/bookkeeper.env
      sed -i -e "s/0.0.0.0:8080/bookkeeper:8080/" "$CONFIG_PATH"/mercure.json
    fi
    
    sed -i -e "s/BOOKKEEPER_TOKEN_PLACEHOLDER/$BOOKKEEPER_SECRET/" "$CONFIG_PATH"/mercure.json
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
    sudo mkdir "$MERCURE_BASE"/processor-keys/
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
    sudo cp $MERCURE_SRC/nomad/mercure-ui.nomad $MERCURE_BASE
    sudo cp $MERCURE_SRC/nomad/policies/anonymous-strict.policy.hcl $MERCURE_BASE
    sudo sed -i "s#SSHPUBKEY#$(cat /opt/mercure/processor-keys/id_rsa.pub)#g"  $MERCURE_BASE/mercure.nomad
    sudo sed -i "s/\\\${IMAGE_TAG}/$IMAGE_TAG/g" $MERCURE_BASE/mercure.nomad
    sudo sed -i "s/\\\${IMAGE_TAG}/$IMAGE_TAG/g" $MERCURE_BASE/mercure-ui.nomad

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
  local overwrite=${1:-false}
  if [ "$overwrite" = true ] || [ ! -f "$MERCURE_BASE"/docker-compose.yml ]; then
    echo "## Copying docker-compose.yml..."
    sudo cp $MERCURE_SRC/docker/docker-compose.yml $MERCURE_BASE
    sudo sed -i -e "s/\\\${DOCKER_GID}/$(getent group docker | cut -d: -f3)/g" $MERCURE_BASE/docker-compose.yml
    sudo sed -i -e "s/\\\${UID}/$(getent passwd mercure | cut -d: -f3)/g" $MERCURE_BASE/docker-compose.yml
    sudo sed -i -e "s/\\\${GID}/$(getent passwd mercure | cut -d: -f4)/g" $MERCURE_BASE/docker-compose.yml

    if [[ -v MERCURE_TAG ]]; then # a custom tag was provided
      sudo sed -i "s/\\\${IMAGE_TAG}/\:$MERCURE_TAG/g" $MERCURE_BASE/docker-compose.yml
    else
      sudo sed -i "s/\\\${IMAGE_TAG}/$IMAGE_TAG/g" $MERCURE_BASE/docker-compose.yml
    fi
    sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.yml
  fi
}

setup_docker_dev () {
  if [ ! -f "$MERCURE_BASE"/docker-compose.override.yml ]; then
    echo "## Copying docker-compose.override.yml..."
    sudo cp $MERCURE_SRC/docker/docker-compose.override.yml $MERCURE_BASE
    sudo sed -i -e "s;MERCURE_SRC;$(readlink -f $MERCURE_SRC)/app;" "$MERCURE_BASE"/docker-compose.override.yml
    if [[ -v MERCURE_TAG ]]; then # a custom tag was provided
      sudo sed -i "s/\\\${IMAGE_TAG}/\:$MERCURE_TAG/g" $MERCURE_BASE/docker-compose.override.yml
    else # no custom tag was provided, use latest
      sudo sed -i "s/\\\${IMAGE_TAG}/\:latest/g" $MERCURE_BASE/docker-compose.override.yml
    fi
    sudo chown $OWNER:$OWNER "$MERCURE_BASE"/docker-compose.override.yml
  fi
}

build_docker () {
  echo "## Building mercure docker containers..."  
  sudo $MERCURE_SRC/build-docker.sh -y
}

start_docker () {
  echo "## Starting docker compose..."  
  pushd $MERCURE_BASE
  sudo docker-compose up -d
  popd
}

link_binaries() {
  sudo find "$MERCURE_BASE/app/bin/ubuntu$UBUNTU_VERSION" -type f -exec ln -f -s {} "$MERCURE_BASE/app/bin" \;
}

install_app_files() {
  local overwrite=${1:-false}
  if [ $DO_DEV_INSTALL = true ]; then 
    if [ -e "$MERCURE_BASE"/app ]; then # app already exists
      if [ -L "$MERCURE_BASE"/app ]; then # it's already linked somewhere
        sudo unlink "$MERCURE_BASE"/app
      else
        read -p "App directory $MERCURE_BASE/app already exists. Delete and link to $MERCURE_SRC/app? " ANS
        if [ "$ANS" != "y" ]; then
          echo "Update aborted."
          exit 1
        fi
        sudo rm -rf "$MERCURE_BASE"/app
      fi
    fi
    echo "## Linking app files..."
    sudo ln -s "$MERCURE_SRC/app" "$MERCURE_BASE"
    sudo chown -h $OWNER:$OWNER ./app
    link_binaries
    sudo chmod g+w "$MERCURE_SRC/app"
    # the mercure user and running user will be in each other's groups
    sudo usermod -aG $OWNER $(logname)
    sudo usermod -aG $(logname) $OWNER
    return
  fi

  if [ "$overwrite" = true ] || [ ! -e "$MERCURE_BASE"/app ]; then
    echo "## Installing app files..."
    [ "$overwrite" = true ] || sudo mkdir "$MERCURE_BASE"/app
    if [ ! "$MERCURE_SRC" -ef "$MERCURE_BASE"/app ]; then
      sudo cp -R "$MERCURE_SRC/app" "$MERCURE_BASE"
    fi
    link_binaries
    sudo chown -R $OWNER:$OWNER "$MERCURE_BASE/app"
  fi
}

install_packages() {
  echo "## Installing Linux packages..."
  sudo apt-get update
  sudo apt-get install -y build-essential wget git dcmtk jq inetutils-ping sshpass rsync postgresql postgresql-contrib libpq-dev git-lfs python3-wheel python3-dev python3 python3-venv sendmail libqt5core5a redis nginx
  if [ $UBUNTU_VERSION == "24.04" ]; then
    sudo apt-get install -y libqt6core6t64 
  else
    sudo apt-get install -y libqt5core5a 
  fi
}

install_dependencies() {
  echo "## Installing Python runtime environment..."
  if [ ! -e "$MERCURE_BASE/env" ]; then
    sudo mkdir "$MERCURE_BASE/env" && sudo chown $USER "$MERCURE_BASE/env"
    python3 -m venv "$MERCURE_BASE/env"
  fi

  echo "## Installing required Python packages..."
  sudo chown -R $OWNER:$OWNER "$MERCURE_BASE/env"
  sudo su $OWNER -c "$MERCURE_BASE/env/bin/pip install --isolated wheel~=0.37.1"
  sudo su $OWNER -c "$MERCURE_BASE/env/bin/pip install --isolated -r \"$MERCURE_BASE/app/requirements.txt\""
}

install_postgres() {
  echo "## Setting up postgres..."
  sudo -u postgres -s <<- EOM
    cd ~
    createuser mercure
    createdb mercure -O mercure
    psql -c "ALTER USER mercure WITH PASSWORD '$DB_PWD';"
EOM
}

install_oauth2_proxy() {
  echo "## Installing OAuth2-proxy..."
  if [ ! -f "/usr/local/bin/oauth2-proxy" ]; then
    OAUTH2_VERSION="v7.5.1"
    wget -O /tmp/oauth2-proxy.tar.gz "https://github.com/oauth2-proxy/oauth2-proxy/releases/download/${OAUTH2_VERSION}/oauth2-proxy-${OAUTH2_VERSION}.linux-amd64.tar.gz"
    tar -xzf /tmp/oauth2-proxy.tar.gz -C /tmp/
    sudo cp "/tmp/oauth2-proxy-${OAUTH2_VERSION}.linux-amd64/oauth2-proxy" /usr/local/bin/
    sudo chmod +x /usr/local/bin/oauth2-proxy
    rm -rf /tmp/oauth2-proxy*
    echo "OAuth2-proxy installed successfully"
  else
    echo "OAuth2-proxy already installed"
  fi
}

install_sso_configuration() {
  echo "## Installing SSO configuration templates..."
  if [ ! -f "$CONFIG_PATH"/nginx.conf ]; then
    sudo cp "$MERCURE_SRC"/installation/nginx.conf.template "$CONFIG_PATH"/nginx.conf
    sudo chown $OWNER:$OWNER "$CONFIG_PATH"/nginx.conf
  fi

  if [ ! -f "$CONFIG_PATH"/oauth2.env ]; then
    sudo cp "$MERCURE_SRC"/docker/oauth.env.example "$CONFIG_PATH"/oauth2.env
    sudo chown $OWNER:$OWNER "$CONFIG_PATH"/oauth2.env
    echo "## Please edit $CONFIG_PATH/oauth2.env with your Azure AD configuration"
  fi
}

install_services() {
  echo "## Installing services..."
  sudo cp -n "$MERCURE_SRC"/installation/*.service /etc/systemd/system
  sudo systemctl daemon-reload
  sudo systemctl enable mercure_bookkeeper.service mercure_cleaner.service mercure_dispatcher.service mercure_receiver.service mercure_router.service mercure_ui.service mercure_processor.service
  sudo systemctl restart mercure_bookkeeper.service mercure_cleaner.service mercure_dispatcher.service mercure_receiver.service mercure_router.service mercure_ui.service mercure_processor.service

  sudo systemctl enable mercure_worker_fast@1.service mercure_worker_fast@2.service mercure_worker_slow@1.service mercure_worker_slow@2.service
  sudo systemctl restart mercure_worker_fast@1.service mercure_worker_fast@2.service mercure_worker_slow@1.service mercure_worker_slow@2.service
}

install_sso_services() {
  echo "## Installing SSO services..."
  # First install regular services
  install_services

  # Stop default nginx if running to avoid conflicts
  sudo systemctl stop nginx || true
  sudo systemctl disable nginx || true

  # Enable and start SSO services
  sudo systemctl enable mercure_oauth2_proxy.service mercure_nginx.service
  sudo systemctl start mercure_oauth2_proxy.service
  sudo systemctl start mercure_nginx.service

  echo "## SSO services installed. Please configure $CONFIG_PATH/oauth2.env before using."
}

systemd_install () {
  echo "## Performing systemd-type mercure installation..."
  create_user
  create_folders
  install_configuration
  sudo cp -n "$MERCURE_SRC"/installation/sudoers/* /etc/sudoers.d/
  install_packages
  install_docker
  install_app_files
  install_dependencies
  install_postgres
  sudo chown -R mercure:mercure "$MERCURE_BASE"
  install_services
}

systemd_sso_install () {
  echo "## Performing systemd-type mercure installation with SSO..."
  create_user
  create_folders
  install_configuration
  install_sso_configuration
  sudo cp -n "$MERCURE_SRC"/installation/sudoers/* /etc/sudoers.d/
  install_packages
  install_oauth2_proxy
  install_docker
  install_app_files
  install_dependencies
  install_postgres
  sudo chown -R mercure:mercure "$MERCURE_BASE"
  install_sso_services
}

docker_install () {
  echo "## Performing docker-type mercure installation..."
  create_user
  create_folders
  install_configuration
  install_docker
  if [ $DOCKER_BUILD = true ]; then
    build_docker
  fi
  setup_docker
  if [ $DO_DEV_INSTALL = true ]; then
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

systemd_update () {
  if [ ! -d $MERCURE_BASE/app ]; then
    echo "ERROR: $MERCURE_BASE/app does not exist; is Mercure installed?"
    exit 1
  fi
  local OLD_VERSION=`cat $MERCURE_BASE/app/VERSION`
  if [ $FORCE_INSTALL != "y" ]; then
    echo "Update mercure from $OLD_VERSION to $VERSION (y/n)?"
    read -p "WARNING: Server may require manual fixes after update. Taking backups beforehand is recommended. " ANS
    if [ "$ANS" != "y" ]; then
      echo "Update aborted."
      exit 0
    fi
  fi
  echo "Updating mercure..."
  local services=("ui" "receiver" "bookkeeper" "dispatcher" "cleaner" "bookkeeper" )
  for service in "${services[@]}"; do
    if systemctl is-active --quiet mercure_$service.service; then
      echo "ERROR: mercure_$service.service is running. Stop mercure first."
      exit 1
    fi
  done
  create_folders
  install_app_files true
  sudo cp -n "$MERCURE_SRC"/installation/sudoers/* /etc/sudoers.d/
  install_packages
  install_dependencies
  install_services
  echo "Update complete."
}

docker_update () {
  if [ ! -f $MERCURE_BASE/docker-compose.yml ]; then
    echo "ERROR: $MERCURE_BASE/docker-compose.yml does not exist; is Mercure installed?"
    exit 1
  fi
  if [ -f $MERCURE_BASE/docker-compose.override.yml ]; then
    echo "ERROR: $MERCURE_BASE/docker-compose.override.yml exists. Updating a dev install is not supported."
    exit 1  
  fi
  if [ $FORCE_INSTALL != "y" ]; then
    echo "Update mercure to ${MERCURE_TAG:-VERSION} (y/n)?"
    read -p "WARNING: Server may require manual fixes after update. Taking backups beforehand is recommended. " ANS
    if [ "$ANS" != "y" ]; then
      echo "Update aborted."
      exit 0
    fi
  fi
  # sudo sed -E "s/(image\: mercureimaging.*?\:).*/\1foo/g" docker-compose.yml 
  pushd $MERCURE_BASE
  sudo docker-compose down || true
  popd
  setup_docker true
  start_docker
}
FORCE_INSTALL="n"

while getopts ":hy" opt; do
  case ${opt} in
    h )
      echo "Usage:"
      echo ""
      echo "    install.sh -h                      Display this help message."
      echo "    install.sh [-y] systemd [-dmbu]    Install as systemd service."
      echo "    install.sh [-y] systemd-sso [-dmbu] Install as systemd service with SSO."
      echo "    install.sh [-y] docker  [-dm]      Install with docker-compose."
      echo "    install.sh [-y] nomad              Install as nomad job."
      echo ""
      echo "Options:   "
      echo "                      -d               Development mode."
      echo "                      -m               Install Metabase for reporting."
      echo "only for systemd:"
      echo "                      -u               Update installation."
      echo "only for docker:"
      echo "                      -b               Build containers."
      echo ""      
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


DO_DEV_INSTALL=false
DOCKER_BUILD=false
DO_OPERATION="install"
INSTALL_ORTHANC=false
INSTALL_METABASE=false
while getopts ":dbuom" opt; do
  case ${opt} in
    o ) 
      INSTALL_ORTHANC=true
      ;;
    m )
      INSTALL_METABASE=true
      ;;
    u )
      DO_OPERATION="update"
      ;;
    d )
      DO_DEV_INSTALL=true
      ;;
    b )
      if [ $INSTALL_TYPE != "docker" ]; then 
        echo "Invalid option for \"$INSTALL_TYPE\": -b" 1>&2
      fi
      DOCKER_BUILD=true
      ;;
    \? )
      echo "Invalid Option for \"$INSTALL_TYPE\": -$OPTARG" 1>&2
      exit 1
      ;;
  esac
done

if [ $DO_DEV_INSTALL == true ] && [ $DO_OPERATION == "update" ]; then 
  echo "Invalid option: cannot update a dev installation" 1>&2
  exit 1
fi

if ([ $INSTALL_TYPE == "systemd" ] || [ $INSTALL_TYPE == "systemd-sso" ]) && [ $DO_OPERATION == "update" ]; then 
  systemd_update
  exit 0
elif [ $INSTALL_TYPE == "docker" ] && [ $DO_OPERATION == "update" ]; then 
  docker_update
  exit 0
fi

if [ $FORCE_INSTALL = "y" ]; then
  echo "Forcing installation"
else
  read -p "Install with $INSTALL_TYPE (y/n)? " ANS
  if [ "$ANS" = "y" ]; then
    echo "Installing mercure..."
  else
    echo "Installation aborted."
    exit 0
  fi
fi

case "$INSTALL_TYPE" in
  systemd )
    systemd_install
    ;;
  systemd-sso )
    systemd_sso_install
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
if [ $INSTALL_ORTHANC == true ]; then 
  echo "Installing Orthanc..."
  pushd addons/orthanc
  sudo docker network create mercure_default || true
  sudo docker-compose up -d
  popd
fi
echo "Installation complete"

if [ $INSTALL_METABASE == true ]; then
  sudo apt-get install -y jq
  echo "Initializing Metabase setup..."
  pushd addons/metabase
  sudo ./metabase_install.sh $INSTALL_TYPE
  popd
fi
# -------- Install Docker ------
echo "Installing Docker..."
sudo apt-get update
sudo apt-get remove docker docker-engine docker.io
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
sudo usermod -a -G docker vagrant
sudo docker --version


# -------- Install Nomad and Consul ------

# Packages required for nomad & consul
sudo apt-get install unzip curl vim build-essential -y 

echo "Installing Nomad..."
NOMAD_VERSION=1.0.1
cd /tmp/
curl -sSL https://releases.hashicorp.com/nomad/${NOMAD_VERSION}/nomad_${NOMAD_VERSION}_linux_amd64.zip -o nomad.zip
unzip nomad.zip
sudo install nomad /usr/bin/nomad
sudo mkdir -p /etc/nomad.d
sudo chmod a+w /etc/nomad.d
(
cat <<-EOFB
  [Unit]
  Description=nomad
  Requires=network-online.target
  After=network-online.target
  [Service]
  Restart=on-failure
  ExecStart=/usr/bin/nomad agent -dev-connect -bind 0.0.0.0 -log-level INFO -config /home/vagrant/mercure/nomad/server.conf
  ExecReload=/bin/kill -HUP 
  [Install]
  WantedBy=multi-user.target
EOFB
) | sudo tee /etc/systemd/system/nomad.service
sudo systemctl enable nomad.service

echo "Installing Consul..."
CONSUL_VERSION=1.9.0
curl -sSL https://releases.hashicorp.com/consul/${CONSUL_VERSION}/consul_${CONSUL_VERSION}_linux_amd64.zip > consul.zip
unzip /tmp/consul.zip
sudo install consul /usr/bin/consul
(
cat <<-EOFA
  [Unit]
  Description=consul agent
  Requires=network-online.target
  After=network-online.target

  [Service]
  Restart=on-failure
  ExecStart=/usr/bin/consul agent -dev
  ExecReload=/bin/kill -HUP $MAINPID

  [Install]
  WantedBy=multi-user.target
EOFA
) | sudo tee /etc/systemd/system/consul.service
sudo systemctl enable consul.service
sudo systemctl start consul

for bin in cfssl cfssl-certinfo cfssljson
do
  echo "Installing $bin..."
  curl -sSL https://pkg.cfssl.org/R1.2/${bin}_linux-amd64 > /tmp/${bin}
  sudo install /tmp/${bin} /usr/local/bin/${bin}
done
nomad -autocomplete-install

curl -L -o cni-plugins.tgz https://github.com/containernetworking/plugins/releases/download/v0.9.1/cni-plugins-linux-amd64-v0.9.1.tgz
sudo mkdir -p /opt/cni/bin
sudo tar -C /opt/cni/bin -xzf cni-plugins.tgz


# -------- Install Mercure ------
echo "Cloning mercure..."
sudo cp /vagrant/mercure_deploy.pem ~/.ssh
sudo chmod 0400 ~/.ssh/mercure_deploy.pem
sudo chown vagrant ~/.ssh/mercure_deploy.pem
cd ~
GIT_SSH_COMMAND='ssh -i ~/.ssh/mercure_deploy.pem -o IdentitiesOnly=yes -o StrictHostKeyChecking=no' git clone git@github.com:mercure-imaging/mercure.git

echo "Installing mercure..."
mkdir ~/mercure-docker
mkdir ~/mercure-docker/processor-keys
echo "Generating SSH key..."
ssh-keygen -t rsa -N '' -f /home/vagrant/mercure-docker/processor-keys/id_rsa

echo "Building mercure core containers..."
cd ~/mercure
sudo su vagrant -c "MERCURE_SECRET=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1) ./build-docker.sh || exit 1"
echo "Done building docker containers..."

cp /vagrant/mercure.json ~/mercure-docker/mercure-config/mercure.json
cd ~/mercure/nomad/
sed -i "s#SSHPUBKEY#$(cat ~/mercure-docker/processor-keys/id_rsa.pub)#g" mercure.nomad

echo "Building mercure processing containers..."
sudo su vagrant -c "cd ~/mercure/nomad/processing && make"
sudo su vagrant -c "cd ~/mercure/nomad/dummy-processor && make"
sudo su vagrant -c "cd ~/mercure/nomad/sshd && make"
echo "Done building processing containers..."

sudo systemctl start nomad
echo "Waiting for Nomad to start..."
until [[ $(curl http://localhost:4646) ]];
do
  echo -n "."
  sleep 1s;
done;


# -------- Start Mercure ------
echo "Starting mercure..."
cd ~/mercure/nomad/
/usr/bin/nomad run mercure.nomad
/usr/bin/nomad run mercure-processor.nomad

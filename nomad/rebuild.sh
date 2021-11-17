cd .. && ./build-docker.sh
cd nomad
/usr/bin/nomad stop mercure
sudo rm -rf /opt/mercure/data/processing/*
/usr/bin/nomad run mercure.nomad

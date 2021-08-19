#!/usr/bin/env bash
set -Eeo pipefail

while getopts ":m:" opt; do
  case ${opt} in
    m )
      mode=$OPTARG
      ;;
    \? )
      echo "Invalid option: $OPTARG" 1>&2
      ;;
    : )
      echo "Invalid option: $OPTARG requires an argument" 1>&2
      ;;
  esac
done

get_data() {
  # todo: make the host key available
    scp -vvv -o StrictHostKeyChecking=no -i /secrets/keys/id_rsa -P $STORAGE_PORT -r root@$STORAGE_IP:/data/processing/$NOMAD_META_PATH/in/ ${NOMAD_ALLOC_DIR}/data/in
    # The following only works if Consul is running with "-client 0.0.0.0" or "client_addr": "0.0.0.0" to listen on all interfaces. 
    curl --request PUT --data 'starting' http://172.17.0.1:8500/v1/kv/status/$NOMAD_META_PATH || true
    mkdir "${NOMAD_ALLOC_DIR}/data/out"
    echo "Data retrieved."
}

put_data() {
  # 172.17.0.1 is the IP address assigned to the host by Docker
  until [[ $(curl http://172.17.0.1:4646/v1/allocation/$NOMAD_ALLOC_ID | jq -r ".TaskStates.process.State") == "dead" ]]; 
  do 
    echo "waiting";
    sleep 10s;
  done; 
  curl --request PUT --data 'processed' http://172.17.0.1:8500/v1/kv/status/$NOMAD_META_PATH || true
  echo "done";
  # rsync -rtz -e "ssh -p $STORAGE_PORT -o StrictHostKeyChecking=no -i /secrets/keys/id_rsa" ${NOMAD_ALLOC_DIR}/data/out/ root@$STORAGE_IP:/data/processing/$NOMAD_META_PATH/out
  scp -o StrictHostKeyChecking=no -i /secrets/keys/id_rsa -P $STORAGE_PORT -r ${NOMAD_ALLOC_DIR}/data/out root@$STORAGE_IP:/data/processing/$NOMAD_META_PATH
  curl --request PUT --data 'complete' http://172.17.0.1:8500/v1/kv/status/$NOMAD_META_PATH || true
  echo "Data sent."
}

echo "Connecting to storage: $STORAGE_IP:$STORAGE_PORT"

case ${mode} in
    in ) 
        get_data
        ;;
    out )
        put_data
        ;;
esac

echo "Done."
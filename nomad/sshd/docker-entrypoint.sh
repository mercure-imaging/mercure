#!/bin/sh

if [ ! -f "/etc/ssh/ssh_host_rsa_key" ]; then
	# generate fresh rsa key
	ssh-keygen -f /etc/ssh/ssh_host_rsa_key -N '' -t rsa
fi
if [ ! -f "/etc/ssh/ssh_host_dsa_key" ]; then
	# generate fresh dsa key
	ssh-keygen -f /etc/ssh/ssh_host_dsa_key -N '' -t dsa
fi

#prepare run dir
if [ ! -d "/var/run/sshd" ]; then
  mkdir -p /var/run/sshd
fi

authorized_keys=$(cat local/ssh/authorized_keys)
if [ $authorized_keys = "SSHPUBKEY" ]; then
  echo "Authorized keys not set. Shutting down."
  echo "Authorized keys not set. Shutting down." 1>&2
  exit 1
fi

exec "$@"

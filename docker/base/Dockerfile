FROM ubuntu:20.04
RUN apt-get update && \
    DEBIAN_FRONTEND="noninteractive" apt-get -y install \
    tzdata build-essential wget git dcmtk jq inetutils-ping entr sshpass lsb-release lsb-core libpq-dev --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -ms /bin/bash mercure && \
    mkdir -p /opt/mercure/app/installation /opt/mercure/app/configuration

WORKDIR /opt/mercure/app

# Note: you must run this Dockerfile from the root directory of the project
COPY ./installation ./installation
COPY ./configuration ./configuration
COPY ./requirements.txt .

# This fixes the install script trying to write the configuration files
# and makes sure we can definitely read everything
RUN chown -R mercure ./configuration && \
    chmod -R o+rx /opt/mercure && \
    ./installation/install-env.sh

# This fixes the issue that every code update rebuilds Conda
COPY ./ .

# The configuration and data folders is probably the only thing that mercure ACTUALLY needs to write to
RUN chmod -R o+rx /opt/mercure/app && \
    chown -R mercure /opt/mercure/config && \
    mkdir -p /opt/mercure/data/incoming \
          /opt/mercure/data/studies \
          /opt/mercure/data/outgoing \
          /opt/mercure/data/success \
          /opt/mercure/data/error \
          /opt/mercure/data/discard \
          /opt/mercure/data/processing && \
    chown -R mercure /opt/mercure/data
# Export the configuration and data folder as a volume, as multiple scripts will have to read/write there
VOLUME /opt/mercure/config
VOLUME /opt/mercure/data
USER mercure
ENV DEBUG=False
ENV MERCURE_CONFIG_FOLDER=/opt/mercure/config
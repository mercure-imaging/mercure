FROM ubuntu:20.04
RUN apt-get update && apt-get -y upgrade && apt-get install -y build-essential wget git dcmtk jq inetutils-ping entr sshpass
RUN useradd -ms /bin/bash mercure
RUN mkdir -p /opt/mercure/app/installation /opt/mercure/app/configuration
# Note: you must run this Dockerfile from the root directory of the project
COPY ./installation /opt/mercure/app/installation
COPY ./configuration /opt/mercure/app/configuration
COPY ./requirements.txt /opt/mercure/app/
# This fixes the install script trying to write the configuration files
RUN chown -R mercure /opt/mercure/app/configuration
# Make sure we can definitely read everything
RUN chmod -R o+rx /opt/mercure
WORKDIR /opt/mercure/app
RUN /opt/mercure/app/installation/install-env.sh
# This fixes the issue that every code update rebuilds Conda
COPY ./ /opt/mercure/app/
RUN chmod -R o+rx /opt/mercure/app

# The configuration and data folders is probably the only thing that mercure ACTUALLY needs to write to
RUN mkdir /opt/mercure/config && chown -R mercure /opt/mercure/config
RUN mkdir -p /opt/mercure/data/incoming \
          /opt/mercure/data/studies \
          /opt/mercure/data/outgoing \
          /opt/mercure/data/success \
          /opt/mercure/data/error \
          /opt/mercure/data/discard \
          /opt/mercure/data/processing
RUN chown -R mercure /opt/mercure/data
# Export the configuration and data folder as a volume, as multiple scripts will have to read/write there
VOLUME /opt/mercure/config
VOLUME /opt/mercure/data
USER mercure
ENV DEBUG=False
ENV MERCURE_CONFIG_FOLDER=/opt/mercure/config
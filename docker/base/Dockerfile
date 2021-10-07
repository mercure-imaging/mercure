FROM ubuntu:18.04
RUN apt-get update && apt-get -y upgrade && apt-get install -y build-essential wget git dcmtk jq inetutils-ping entr sshpass
RUN useradd -ms /bin/bash mercure
RUN mkdir -p /home/mercure/mercure/installation /home/mercure/mercure/configuration
# Note: you must run this Dockerfile from the root directory of the project
COPY ./installation /home/mercure/mercure/installation
COPY ./configuration /home/mercure/mercure/configuration
COPY ./requirements.txt /home/mercure/mercure/
# This fixes the install script trying to write the configuration files
RUN chown -R mercure /home/mercure/mercure/configuration
# Make sure we can definitely read everything
RUN chmod -R o+rx /home/mercure/mercure
USER mercure
WORKDIR /home/mercure/mercure
RUN /home/mercure/mercure/installation/install.sh
# Switch back to root
USER root
# This fixes the issue that every code update rebuilds Conda
COPY ./ /home/mercure/mercure/
RUN chmod -R o+rx /home/mercure/mercure

# The configuration and data folders is probably the only thing that mercure ACTUALLY needs to write to
RUN mkdir /home/mercure/mercure-config && chown -R mercure /home/mercure/mercure-config
RUN mkdir -p /home/mercure/mercure-data/incoming \
          /home/mercure/mercure-data/studies \
          /home/mercure/mercure-data/outgoing \
          /home/mercure/mercure-data/success \
          /home/mercure/mercure-data/error \
          /home/mercure/mercure-data/discard \
          /home/mercure/mercure-data/processing
RUN chown -R mercure /home/mercure/mercure-data
# Export the configuration and data folder as a volume, as multiple scripts will have to read/write there
VOLUME /home/mercure/mercure/configuration
VOLUME /home/mercure/mercure-data
USER mercure
ENV DEBUG=False
ENV MERCURE_CONFIG_FOLDER=/home/mercure/mercure-config
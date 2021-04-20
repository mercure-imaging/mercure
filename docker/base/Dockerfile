FROM ubuntu:18.04
RUN apt update && apt -y upgrade && apt install -y build-essential wget git dcmtk jq inetutils-ping
RUN useradd -ms /bin/bash mercure
RUN mkdir -p /home/mercure/mercure/installation /home/mercure/mercure/configuration
# Note: you must run this Dockerfile from the root directory of the project
COPY ./installation /home/mercure/mercure/installation
COPY ./configuration /home/mercure/mercure/configuration
COPY ./requirements.txt /home/mercure/mercure/
# This fixes the install script trying to write the configuration files
RUN chown -R mercure /home/mercure/mercure/configuration
USER mercure
WORKDIR /home/mercure/mercure
RUN /home/mercure/mercure/installation/install.sh
# Switch back to root
USER root
# This fixes the issue that every code update rebuilds Conda
COPY ./ /home/mercure/mercure/
# The configuration and data folders is probably the only thing that mercure ACTUALLY needs to write to
RUN chown -R mercure /home/mercure/mercure/configuration
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
ENV DEBUG=False
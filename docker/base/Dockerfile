FROM ubuntu:18.04
RUN apt update && apt -y upgrade && apt install -y build-essential wget git dcmtk jq
RUN useradd -ms /bin/bash mercure
RUN mkdir -p /home/mercure/mercure
# Note: you must run this Dockerfile from the root directory of the project
COPY ./ /home/mercure/mercure/
# This fixes the script trying to write the configuration files
RUN chown -R mercure /home/mercure/mercure/configuration
USER mercure
WORKDIR /home/mercure/mercure
RUN /home/mercure/mercure/installation/install.sh
USER root
RUN mkdir /home/mercure/mercure-data
RUN mkdir /home/mercure/mercure-data/incoming \
          /home/mercure/mercure-data/studies \
          /home/mercure/mercure-data/outgoing \
          /home/mercure/mercure-data/success \
          /home/mercure/mercure-data/error \
          /home/mercure/mercure-data/discard \
          /home/mercure/mercure-data/processing
# Export the configuration and data folder as a volume, as multiple scripts will have to read/write there
VOLUME /home/mercure/mercure/configuration
VOLUME /home/mercure/mercure-data
ENV DEBUG=False
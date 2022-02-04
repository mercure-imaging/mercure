ARG VERSION_TAG=latest
FROM mercureimaging/mercure-base:$VERSION_TAG
USER root
RUN apt-get install -y lsb-core
USER mercure
EXPOSE 11112
CMD /opt/mercure/app/receiver.sh

FROM mercureimaging/mercure-base:latest
USER root
RUN apt-get update && apt-get install -y lsb-core
USER mercure
EXPOSE 11112
CMD /opt/mercure/app/receiver.sh

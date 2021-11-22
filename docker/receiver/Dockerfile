FROM mercureimaging/mercure-base:latest
USER root
RUN apt install lsb-core
USER mercure
EXPOSE 11112
CMD /opt/mercure/app/receiver.sh

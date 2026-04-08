ARG VERSION_TAG=latest
ARG BASE_IMAGE_NAME=mercureimaging/mercure-base
FROM $BASE_IMAGE_NAME:$VERSION_TAG

SHELL ["/bin/bash", "-c"]
CMD /opt/mercure/env/bin/rq worker $WORKER_QUEUE --with-scheduler

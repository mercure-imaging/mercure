ARG VERSION_TAG=latest
ARG IMAGE_NAME=mercureimaging/mercure-base
FROM $IMAGE_NAME:$VERSION_TAG

SHELL ["/bin/bash", "-c"]
CMD /opt/mercure/env/bin/rq worker $WORKER_QUEUE --url $REDIS_URL --with-scheduler

ARG VERSION_TAG=latest
ARG IMAGE_NAME=mercureimaging/mercure-base
FROM $IMAGE_NAME:$VERSION_TAG
CMD /opt/mercure/env/bin/rq worker $WORKER_QUEUE --url $REDIS_URL --with-scheduler

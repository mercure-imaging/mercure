ARG VERSION_TAG=latest
ARG BASE_IMAGE_NAME=mercureimaging/mercure-base
FROM $BASE_IMAGE_NAME:$VERSION_TAG
CMD ["/opt/mercure/env/bin/python", "-u", "/opt/mercure/app/processor.py"]

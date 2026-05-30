ARG VERSION_TAG=latest
ARG BASE_IMAGE_NAME=mercureimaging/mercure-base
FROM $BASE_IMAGE_NAME:$VERSION_TAG
EXPOSE 8080
HEALTHCHECK CMD wget -O/dev/null -q http://localhost:8080/test || exit 1
CMD ["/opt/mercure/env/bin/python", "/opt/mercure/app/bookkeeper.py"]

ARG VERSION_TAG=latest
FROM mercureimaging/mercure-base:$VERSION_TAG
EXPOSE 8080
HEALTHCHECK CMD wget -O/dev/null -q http://localhost:8080/test || exit 1
CMD /opt/mercure/env/bin/python /opt/mercure/app/bookkeeper.py

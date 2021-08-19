FROM alpine:3.11
RUN apk add --no-cache \
  bash

ADD docker-entrypoint.sh ./
CMD ["./docker-entrypoint.sh"]
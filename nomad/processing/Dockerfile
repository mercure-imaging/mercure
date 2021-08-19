FROM alpine:3.11
RUN apk add --no-cache \
  openssh-client \
  ca-certificates \
  bash jq curl rsync

ADD docker-entrypoint.sh ./

CMD ["./docker-entrypoint.sh"]
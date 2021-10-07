FROM alpine:3.11
RUN apk add --no-cache \
  openssh-client \
  ca-certificates \
  bash jq curl rsync

RUN addgroup --gid 1000 mercure && adduser \
    --disabled-password \
    --gecos "" \
    --ingroup "mercure" \
    --uid "1000" \
    "mercure"

ADD docker-entrypoint.sh ./

CMD ["./docker-entrypoint.sh"]
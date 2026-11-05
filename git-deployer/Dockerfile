ARG BUILD_FROM
FROM $BUILD_FROM

# hadolint ignore=DL3018
RUN apk add --no-cache git python3 py3-yaml

COPY root /
RUN chmod a+x /run.sh /deploy.py
ENTRYPOINT [ "/run.sh" ]

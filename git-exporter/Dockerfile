ARG BUILD_FROM
FROM $BUILD_FROM AS build

# git-secrets is pinned to a commit (tag 1.3.0), not just a tag, because tags can be moved.
ARG GIT_SECRETS_COMMIT=ad82d68ee924906a0401dfd48de5057731a9bc84

# hadolint ignore=DL3018
RUN apk add --no-cache git make \
    && git clone https://github.com/awslabs/git-secrets.git /git-secrets \
    && cd /git-secrets \
    && git -c advice.detachedHead=false checkout "${GIT_SECRETS_COMMIT}" \
    && test "$(git rev-parse HEAD)" = "${GIT_SECRETS_COMMIT}" \
    && make install

FROM $BUILD_FROM AS running

# Packages come from the pinned Alpine release of the base image.
# PyYAML is installed from apk so no pip (and no unpinned PyPI download) is needed.
# hadolint ignore=DL3018
RUN apk add --no-cache git rsync grep sed python3 py3-yaml findutils

COPY --from=build /usr/local/bin/git-secrets /usr/local/bin/git-secrets

COPY root /
RUN chmod a+x /run.sh /utils/*
ENTRYPOINT [ "/run.sh" ]

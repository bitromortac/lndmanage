# for optimized python builds
# we follow solution #2 described in https://pythonspeed.com/articles/multi-stage-docker-python/

FROM python:3.10-slim as builder

RUN python -m venv /root/.venv

ENV PATH="/root/.venv/bin:$PATH"

ARG LNDMANAGE_HOST_SRC_PATH=.

COPY "$LNDMANAGE_HOST_SRC_PATH/requirements.txt" .
COPY "$LNDMANAGE_HOST_SRC_PATH/pyproject.toml" .
COPY "$LNDMANAGE_HOST_SRC_PATH/setup.py" .
COPY "$LNDMANAGE_HOST_SRC_PATH/lndmanage/__init__.py" ./lndmanage/

RUN pip install .

# ---------------------------------------------------------------------------------------------------------------------------

FROM python:3.10-slim as final

ARG LNDMANAGE_EXTRA_PACKAGES
RUN ([ ! -z $LNDMANAGE_EXTRA_PACKAGES ] && \
	apt-get update && \
	apt-get install -y --no-install-recommends ${LNDMANAGE_EXTRA_PACKAGES} && \
	apt-get clean && rm -rf /var/lib/apt/lists/*) || true

# this is for better handling docker-compose signals
ARG TINI_VERSION=v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini
ENTRYPOINT ["/tini", "--"]

# copy python environment from builder
COPY --from=builder /root/.venv /root/.venv

ENV PATH="/root/.venv/bin:$PATH:/root"
ENV TLS_CERT_FILE /root/aux/tls.cert
ENV ADMIN_MACAROON_FILE /root/aux/admin.macaroon

ARG DATE_ARG=""
ARG BUILD_ARG=0
ARG VERSION_ARG="0.0"
ENV VERSION=$VERSION_ARG

LABEL org.opencontainers.image.title="LND Manage"
LABEL org.opencontainers.image.created=${DATE_ARG}
LABEL org.opencontainers.image.revision=${BUILD_ARG}
LABEL org.opencontainers.image.version=${VERSION_ARG}
LABEL org.opencontainers.image.source="https://github.com/dobtc/lndmanage/"
LABEL org.opencontainers.image.url="https://hub.docker.com/r/dobtc/lndmanage/"
LABEL org.opencontainers.image.description="Channel management tool for lightning network daemon (LND) operators"

# copy sources under /root/lndmanage
WORKDIR /root/lndmanage
ARG LNDMANAGE_HOST_SRC_PATH=.
COPY "$LNDMANAGE_HOST_SRC_PATH" .

WORKDIR /root
COPY "$LNDMANAGE_HOST_SRC_PATH/docker/home" .

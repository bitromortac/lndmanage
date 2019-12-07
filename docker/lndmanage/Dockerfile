# for optimized python builds
# we follow solution #2 described in https://pythonspeed.com/articles/multi-stage-docker-python/

FROM python:3 as builder

RUN python -m venv /root/.venv

ENV PATH="/root/.venv/bin:$PATH"

ARG LNDMANAGE_HOST_SRC_PATH

COPY "$LNDMANAGE_HOST_SRC_PATH/requirements.txt" .

RUN pip install -r requirements.txt

# ---------------------------------------------------------------------------------------------------------------------------

FROM python:3-slim as final

# install fish shell for convenience
RUN apt-get update && apt-get install -y --no-install-recommends \
		fish

# this is for better handling docker-compose signals
ENV TINI_VERSION v0.18.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini
ENTRYPOINT ["/tini", "--"]


# copy python environment from builder
COPY --from=builder /root/.venv /root/.venv

ENV PATH="/root/.venv/bin:$PATH:/root"

# copy sources under /root/lndmanage
WORKDIR /root/lndmanage
ARG LNDMANAGE_HOST_SRC_PATH
COPY "$LNDMANAGE_HOST_SRC_PATH" .

# this should be fast because it is cached from builder image
RUN pip install -r requirements.txt

WORKDIR /root
COPY "home" .
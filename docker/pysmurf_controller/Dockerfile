FROM simonsobs/so_smurf_base:v0.0.9

# Download and extract just the Docker CLI binary
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-24.0.2.tgz \
    | tar -xz -C /tmp \
    && mv /tmp/docker/docker /usr/local/bin/ \
    && rm -rf /tmp/docker

# Create the docker group
ARG DOCKER_GID=999
RUN groupadd -g ${DOCKER_GID} docker && \
    usermod -aG docker cryo

#################################################################
# sodetlib Install
#################################################################
WORKDIR /
RUN git clone --branch v0.6.7 --depth 1 https://github.com/simonsobs/sodetlib.git
# allow versioneer to determine sodetlib version safely
USER cryo
RUN git config --global --add safe.directory /sodetlib
USER root
WORKDIR /sodetlib
RUN pip3 install -U pip
RUN pip3 install -e .
RUN pip3 install -r requirements.txt
# Pin version until base image is on a more modern Python version
RUN pip3 install setuptools-scm==9.2.2

ENV OCS_CONFIG_DIR=/config

ENV PYTHONUNBUFFERED=1

# SOCS installation
RUN python3 -m pip install git+https://github.com/simonsobs/socs.git@main

RUN python3 -m pip install dumb-init

ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

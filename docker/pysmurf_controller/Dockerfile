FROM simonsobs/sodetlib:v0.5.0

ENV OCS_CONFIG_DIR /config

# SOCS installation
RUN python3 -m pip install git+https://github.com/simonsobs/socs.git@develop

RUN pip3 install dumb-init

ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

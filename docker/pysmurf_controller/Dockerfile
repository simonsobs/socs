FROM simonsobs/sodetlib:v0.4.0

WORKDIR /app

ENV OCS_CONFIG_DIR /config

# SOCS installation
RUN python3 -m pip install --src=/app/ -e git+https://github.com/simonsobs/socs.git@py36#egg=socs

RUN pip3 install dumb-init

ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

FROM simonsobs/sodetlib:v0.5.2-20-gdd529b5

ENV OCS_CONFIG_DIR /config

ENV PYTHONUNBUFFERED=1

# SOCS installation
RUN python3 -m pip install git+https://github.com/simonsobs/socs.git@main

RUN pip3 install dumb-init

ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

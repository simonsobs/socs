FROM simonsobs/so_smurf_base:v0.0.6

#################################################################
# sodetlib Install
#################################################################
WORKDIR /
RUN git clone --branch v0.5.4 --depth 1 https://github.com/simonsobs/sodetlib.git
WORKDIR /sodetlib
RUN pip3 install -e .
RUN pip3 install -r requirements.txt

ENV OCS_CONFIG_DIR /config

ENV PYTHONUNBUFFERED=1

# SOCS installation
RUN python3 -m pip install git+https://github.com/simonsobs/socs.git@main

RUN python3 -m pip install dumb-init

ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

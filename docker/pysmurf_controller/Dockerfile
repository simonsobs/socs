FROM simonsobs/so_smurf_base:rogue6-rc5

#################################################################
# sodetlib Install
#################################################################
WORKDIR /
RUN git clone https://github.com/simonsobs/sodetlib.git
# allow versioneer to determine sodetlib version safely
USER cryo
RUN git config --global --add safe.directory /sodetlib
USER root
WORKDIR /sodetlib
RUN git checkout 4cad0395d4f2702037848a938052c1aa3  # tpm/rogue6
RUN pip3 install -U pip
RUN pip3 install -e .
RUN pip3 install -r requirements.txt
# Pin version until base image is on a more modern Python version
RUN pip3 install setuptools-scm==9.2.2

ENV OCS_CONFIG_DIR=/config

ENV PYTHONUNBUFFERED=1

# SOCS installation
RUN python3 -m pip install git+https://github.com/simonsobs/socs.git@tpm/rogue6

RUN python3 -m pip install dumb-init

ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

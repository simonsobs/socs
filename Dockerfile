# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.11.1

# Set up the cryo/smurf user and group so this can run on smurf-servers
# See link for how all other smurf-containers are set up:
#   https://github.com/slaclab/smurf-base-docker/blob/master/Dockerfile
RUN useradd -d /home/cryo -M cryo -u 1000 && \
    groupadd smurf -g 1001 && \
    usermod -aG smurf cryo && \
    usermod -g smurf cryo && \
    mkdir /home/cryo && \
    chown cryo:smurf /home/cryo

# Install packages
# suprsync agent - rsync
# labjack agent - wget, python3-pip, libusb-1.0-0-dev, udev
RUN apt-get update && apt-get install -y rsync \
    wget \
    python3-pip \
    libusb-1.0-0-dev \
    udev

# Install labjack ljm module
# Copied from the labjack ljm dockerfile:
# https://hub.docker.com/r/labjack/ljm/dockerfile
WORKDIR /app/labjack/
RUN wget https://cdn.docsie.io/file/workspace_u4AEu22YJT50zKF8J/doc_VDWGWsJAhd453cYSI/boo_9BFzMKFachlhscG9Z/file_NNCdkmsmvPHtgkHk8/labjack_ljm_software_2020_03_30_x86_64_betatar.gz -O labjack_ljm_software_2020_03_30_x86_64_beta.tar.gz
RUN tar zxf ./labjack_ljm_software_2020_03_30_x86_64_beta.tar.gz
RUN ./labjack_ljm_software_2020_03_30_x86_64/labjack_ljm_installer.run -- --no-restart-device-rules

# Copy in and install requirements
COPY requirements/ /app/socs/requirements
COPY requirements.txt /app/socs/requirements.txt
WORKDIR /app/socs/
# Work around https://github.com/pypa/setuptools/issues/4483/ temporarily
RUN pip3 install -U "setuptools<71.0.0"
RUN pip3 install -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app/socs/

# Install socs
RUN pip3 install .

# Reset workdir to avoid local imports
WORKDIR /

# Port for HWP Encoder Beaglebone connection
EXPOSE 8080/udp

# Run agent on container startup
ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

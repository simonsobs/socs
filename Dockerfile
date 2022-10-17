# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.10.0

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
RUN wget https://labjack.com/sites/default/files/software/labjack_ljm_minimal_2020_03_30_x86_64_beta.tar.gz
RUN tar zxf ./labjack_ljm_minimal_2020_03_30_x86_64_beta.tar.gz
RUN ./labjack_ljm_minimal_2020_03_30_x86_64/labjack_ljm_installer.run -- --no-restart-device-rules
RUN pip3 install --no-cache-dir https://labjack.com/sites/default/files/software/Python_LJM_2019_04_03.zip

# Copy in and install requirements
COPY requirements/ /app/socs/requirements
COPY requirements.txt /app/socs/requirements.txt
WORKDIR /app/socs/
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

# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.9.3

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
RUN apt-get update && apt-get install -y rsync  # suprsync

# Copy the current directory contents into the container at /app
COPY . /app/socs/

WORKDIR /app/socs/

# Install socs
RUN pip3 install -r requirements.txt && \
    pip3 install .

# Reset workdir to avoid local imports
WORKDIR /

# Port for HWP Encoder Beaglebone connection
EXPOSE 8080/udp

# Run agent on container startup
ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

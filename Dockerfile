# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.6.0-1-g569b428

# Copy the current directory contents into the container at /app
COPY . /app/socs/

WORKDIR /app/

# Install socs
RUN pip3 install -r socs/requirements.txt \
    && pip3 install -e socs



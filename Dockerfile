# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.5.0-49-g0eb536c

# Copy the current directory contents into the container at /app
COPY . /app/socs/

WORKDIR /app/

# Install socs
RUN pip3 install -r socs/requirements.txt \
    && pip3 install -e socs



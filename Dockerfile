# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.8.0

# Copy the current directory contents into the container at /app
COPY . /app/socs/

WORKDIR /app/socs/

# Install socs
RUN pip3 install -r requirements.txt && \
    pip3 install -e .

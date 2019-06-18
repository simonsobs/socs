# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM grumpy.physics.yale.edu/ocs:v0.5.0-30-g4d4dcd0

# Set the working directory to /app_socs
WORKDIR /app_socs

# Copy the current directory contents into the container at /app
COPY . /app_socs/

# Install socs
RUN pip3 install -r requirements.txt .

# socs-docker
# A container setup with an installation of socs.

# Use the ocs image as a base
FROM simonsobs/ocs:v0.5.0-42-ge9c1234

# Set the working directory to /app_socs
WORKDIR /app_socs

# Copy the current directory contents into the container at /app
COPY . /app_socs/

# Install socs
RUN pip3 install -r requirements.txt .

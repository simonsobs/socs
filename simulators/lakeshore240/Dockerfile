# SOCS Lakeshore 240 Simulator
# Software simulator for a Lakeshore 240, emulating interaction with hardware.

# Use socs base image
FROM socs:latest

# Set the working directory
WORKDIR /app/socs/simulators/lakeshore240/

# Copy into the app directory
COPY . .

# Run simulator on container startup
ENTRYPOINT ["python3", "-u", "ls240_simulator.py"]

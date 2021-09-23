# SOCS Lakeshore 372 Simulator
# Simulated Lakeshore 372 hardware.

# Use socs base image
FROM socs:latest

# Default port for 372
EXPOSE 7777

# Set the working directory to registry directory
WORKDIR /app/socs/simulators/lakeshore372/

# Copy the simulator into the app/simulators directory
COPY . .

# Run simulator on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "ls372_simulator.py"]

# Sensible default arguments
CMD ["-p", "7777"]

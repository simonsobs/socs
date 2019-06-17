# SOCS Lakeshore 240 Agent
# socs Agent container for interacting with a Lakeshore 240.

# Use ocs base image
FROM grumpy.physics.yale.edu/ocs:latest

# Set the working directory to registry directory
WORKDIR /app/agents/smurf-stream-simulator/

# Copy this agent into the app/agents directory
COPY . /app/agents/smurf-stream-simulator/

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "smurf-stream-simulator.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

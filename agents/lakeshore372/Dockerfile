# SOCS Lakeshore 372 Agent
# socs Agent container for interacting with a Lakeshore 372.

# Use ocs base image
FROM grumpy.physics.yale.edu/ocs:latest

# Set the working directory to registry directory
WORKDIR /app/agents/lakeshore372/

# Copy this agent into the app/agents directory
COPY . /app/agents/lakeshore372/

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "LS372_agent.py"]

# SOCS Lakeshore 240 Agent
# socs Agent container for interacting with a Lakeshore 240.

# Use ocs base image
FROM grumpy.physics.yale.edu/ocs:latest

# Set the working directory to registry directory
WORKDIR /app/agents/lakeshore240/

# Copy this agent into the app/agents directory
COPY . /app/agents/lakeshore240/

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "LS240_agent.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

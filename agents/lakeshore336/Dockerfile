# SOCS Lakeshore 336 Agent
# socs Agent container for interacting with a Lakeshore 336.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/lakeshore336/

# Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "LS336_agent.py"]

# Sensible default arguments
CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

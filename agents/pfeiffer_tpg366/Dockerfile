# SOCS Pfeiffer TPG-366  Agent
# socs Agent container for interacting with a Pfeiffer TPG-366 pressure gauge reader.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/pfeiffer_tpg366/

# Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "pfeiffer_tpg366_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

# SOCS Honeywell HMR2300 Agent

# Use socs base image
FROM socs:latest

# Set the working directory
WORKDIR /app/socs/agents/honeywell_HMR2300/

# Copy in the Agent
COPY . .

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "honeywell_HMR2300.py"]

# Default site-hub
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

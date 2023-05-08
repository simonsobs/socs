#SOCS FTS aerotech motor stage

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/fts_aerotech_stage/

## Copy this agent into the app/agents directory
COPY . /app/socs/agents/fts_aerotech_stage/

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "fts_aerotech_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]
# SOCS PTC Agent

# SOCS Agent container for interacting with PTC over ethernet
# Use socs base image

FROM socs:latest

# Set the working directory to registry directory

WORKDIR /app/socs/agents/cryomech-cpa/

# Copy this agent into the app/socs/agents directory

COPY . /app/socs/agents/cryomech-cpa/

# Run agent on container startup

ENTRYPOINT ["python3", "-u", "cryomech_cpa_agent.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

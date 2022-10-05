# SOCS Polarizing Grid Rotator Motor Agent
# socs Agent container for interacting with Grid Rotator Motor via
# serial communication with a MOXA box.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/pgrid_motor/

## Copy this agent into the app/agents directory
COPY . /app/socs/agents/pgrid_motor/

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "pgrid_motor_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

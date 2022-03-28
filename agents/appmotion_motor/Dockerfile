# SOCS Applied Motion Motor Controller Agent
# socs Agent container for interacting with Applied Motion ST5-Q-NE Motor Steppers via
# serial communication with a MOXA box.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/app_motionmotor/

## Copy this agent into the app/agents directory
COPY . /app/socs/agents/app_motionmotor/

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "sat1_motors_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

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
ENTRYPOINT ["python3", "-u", "appmotion_agent.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

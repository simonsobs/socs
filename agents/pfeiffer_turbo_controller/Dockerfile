# SOCS Turbo Controller Agent
# socs Agent container for interacting with Pfeiffer Turbo Controller using a moxa serial to ethernet controller
# converts.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/pfeiffer_turbo_controller/

## Copy this agent into the app/agents directory
COPY . .

# Run agent on container startup
ENTRYPOINT ["python3", "-u", "Pfeiffer_Turbo_Controller_Agent.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

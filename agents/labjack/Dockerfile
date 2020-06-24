# SOCS LabJack Agent
# socs Agent container for running the LabJack Agent.

# Use socs base image
FROM socs:latest

# Set the working directory to proper agent directory
WORKDIR /app/socs/agents/labjack/

## Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "labjack_agent.py"]

# Sensible default arguments
CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

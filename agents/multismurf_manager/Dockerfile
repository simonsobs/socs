
# SOCS Synaccess Agent, used to run the Synaccess power strip

# Use socs base image
FROM socs:latest

# Set the working directory to proper agent directory
WORKDIR /app/socs/agents/multi_smurf_manager

## Copy this agent into the app/agents directory
COPY . .


# Run registry on container startup
ENTRYPOINT ["python3", "-u", "multismurf_manager.py"]

# Sensible default arguments
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

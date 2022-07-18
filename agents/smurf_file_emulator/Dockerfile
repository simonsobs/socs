# SMuRF File Emulator Agent docker

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/smurf_file_emulator/

# Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "smurf_file_emulator.py"]

# Sensible default arguments
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

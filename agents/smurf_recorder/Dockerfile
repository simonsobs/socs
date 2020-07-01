# SOCS SMuRF Recorder

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/smurf_recorder/
COPY . .

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "smurf_recorder.py"]

# Default site-hub
CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

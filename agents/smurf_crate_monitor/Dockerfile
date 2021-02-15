# OCS Registry Agent
# ocs Agent container for running the registry.

# Use ocs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/smurf_crate_monitor/

COPY . .

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "smurf_crate_monitor.py"]

# Sensible defaults for setup with sisock
CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

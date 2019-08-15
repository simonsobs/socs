# SOCS Bluefors Agent
# socs Agent container for running the Bluefors log tracking Agent.

# Use socs base image
FROM socs:latest

# Set the working directory to proper agent directory
WORKDIR /app/socs/agents/bluefors/

## Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "bluefors_log_tracker.py"]

# Sensible default instance-id
CMD ["--instance-id=bluefors"]

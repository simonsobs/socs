# SOCS Pfeiffer tc400 Agent
# socs Agent container for interacting with Pfeiffer TC 400 electronic drive unit
# using a moxa serial to ethernet controller converter.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/pfeiffer_tc400/

# Copy and install requirements
COPY requirements.txt .
RUN pip3 install -r requirements.txt

## Copy this agent into the app/agents directory
COPY . .

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "pfeiffer_tc400_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

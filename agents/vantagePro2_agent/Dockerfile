# SOCS Weather Monitor Agent
# socs Agent container for interacting with the Vantrage Pro2 Weather Monitor.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/vantage_pro2/

# Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "vantage_pro2_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

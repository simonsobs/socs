# SOCS AWG Agent
# socs Agent container for interacting with AWG over GPIB to Ethernet
# converts.

# Use socs base image
FROM simonsobs/socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/wiregrid_kikusui/

## Copy this agent into the app/agents directory
COPY . .

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "kikusui_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

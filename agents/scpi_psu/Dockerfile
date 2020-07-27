# SOCS PSU Agent
# socs Agent container for interacting with PSUs over GPIB to Ethernet

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/scpi_psu/

## Copy this agent into the app/agents directory
COPY . .

# Run agent on container startup
ENTRYPOINT ["python3", "-u", "scpi_psu_agent.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

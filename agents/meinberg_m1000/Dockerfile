# SOCS Meinberg M1000 Agent

# Use socs base image
FROM socs:latest

# Set the working directory
WORKDIR /app/socs/agents/meinberg_m1000/

# Copy in the Agent
COPY meinberg_m1000_agent.py .

# Avoid build error from successive COPY's
# https://stackoverflow.com/a/62409523
RUN true

# Copy in the MIBS
COPY mibs/ /usr/local/lib/python3.6/dist-packages/pysnmp/smi/mibs/

# Run agent on container startup
ENTRYPOINT ["python3", "-u", "meinberg_m1000_agent.py"]

# Default site-hub
CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

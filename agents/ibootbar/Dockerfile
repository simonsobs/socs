# SOCS ibootbar Agent

# Use socs base image
FROM socs:latest

# Set the working directory
WORKDIR /app/socs/agents/ibootbar/

# Copy in the Agent
COPY ibootbar.py .

# Avoid build error from successive COPY's
# https://stackoverflow.com/a/62409523
RUN true

# Copy in the MIBS
COPY mibs/ /root/.pysnmp/mibs/

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "ibootbar.py"]

# Default site-hub
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

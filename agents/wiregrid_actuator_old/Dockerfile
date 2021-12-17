# SOCS Wire-Grid Actuator Agent
# socs Agent container for controlling the actuator of wire grid loader 
# This agent should be run in the beaglebone in the electronics box for wire grid loader.

# Use socs base image
#!! This agents should be build from OCS image build in "arm" OS
#FROM socs:latest
FROM ocs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/wiregrid_actuator/

## Copy this agent into the app/agents directory
COPY . .

RUN python3 -m pip install -r requirements.txt

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "wiregrid_actuator.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

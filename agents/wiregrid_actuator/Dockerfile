# SOCS AWG Agent
# socs Agent container for interacting with AWG over GPIB to Ethernet
# converts.

# Use socs base image
#FROM socs:latest
FROM ocs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/wiregrid_actuator/

## Copy this agent into the app/agents directory
COPY . .

#RUN pip3 install -r requirements.txt
RUN apt-get install -y python3-pip && \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt


# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "wiregrid_actuator.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

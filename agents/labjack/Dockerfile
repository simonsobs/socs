# SOCS LabJack Agent
# socs Agent container for running the LabJack Agent.

# Use socs base image
FROM socs:latest

# Set the working directory to proper agent directory
WORKDIR /app/socs/agents/labjack/

# Install ljm module from labjack, copied from the labjack ljm dockerfile 
# located at https://hub.docker.com/r/labjack/ljm/dockerfile
RUN apt-get update
RUN apt-get install -y wget python3-pip libusb-1.0-0-dev udev

RUN wget https://labjack.com/sites/default/files/software/labjack_ljm_minimal_2020_03_30_x86_64_beta.tar.gz
RUN tar zxf ./labjack_ljm_minimal_2020_03_30_x86_64_beta.tar.gz
RUN ./labjack_ljm_minimal_2020_03_30_x86_64/labjack_ljm_installer.run -- --no-restart-device-rules

RUN pip3 install --no-cache-dir https://labjack.com/sites/default/files/software/Python_LJM_2019_04_03.zip

## Copy this agent into the app/agents directory
COPY . .
RUN pip3 install -r requirements.txt

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "labjack_agent.py"]

# Sensible default arguments
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

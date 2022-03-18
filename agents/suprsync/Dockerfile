# SupRsync docker file
FROM socs:latest

# Sets up the cryo / smurf user and group so this can run on smurf-servers
# See link for how all other smurf-containers are set up: 
#   https://github.com/slaclab/smurf-base-docker/blob/master/Dockerfile
RUN useradd -d /home/cryo -M cryo -u 1000 && \
    groupadd smurf -g 1001 && \
    usermod -aG smurf cryo && \
    usermod -g smurf cryo && \
    mkdir /home/cryo && \
    chown cryo:smurf /home/cryo

# Set the working directory to registry directory
WORKDIR /app/socs/agents/suprsync
# Copy this agent into the app/agents directory
RUN apt-get update && apt-get install -y rsync
COPY . .
RUN pip3 install -r requirements.txt

USER cryo:smurf

ENTRYPOINT ["dumb-init", "python3", "-u", "suprsync.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

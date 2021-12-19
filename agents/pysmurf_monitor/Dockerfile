# SOCS Pysmurf Monitor agent
# socs Agent for monitoring Pysmurf Publisher, and writing file info to database.

# Use socs base image
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
WORKDIR /app/socs/agents/pysmurf_monitor/

# Copy this agent into the app/agents directory
COPY . .
RUN pip3 install -r requirements.txt

USER cryo:smurf

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "pysmurf_monitor.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

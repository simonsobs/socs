# SOCS Pysmurf Archiver
# socs Agent for copying pysmurf data files and plots to archive

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/pysmurf_archiver/
# Copy this agent into the app/agents directory
COPY . .

RUN apt-get install rsync -y

RUN pip3 install -r requirements.txt

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "pysmurf_archiver_agent.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

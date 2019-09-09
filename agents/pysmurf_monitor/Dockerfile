# SOCS Pysmurf Monitor agent
# socs Agent for monitoring Pysmurf Publisher, and writing file info to database.

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/pysmurf_monitor/

# Copy this agent into the app/agents directory
COPY . .
RUN pip3 install -r requirements.txt


# Run registry on container startup
ENTRYPOINT ["python3", "-u", "pysmurf_monitor.py"]

CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

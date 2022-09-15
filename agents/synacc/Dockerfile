# SOCS Synaccess Agent, used to run the Synaccess power strip

# Use socs base image
FROM socs:latest

# Set the working directory to proper agent directory
WORKDIR /app/socs/agents/synacc/

## Copy this agent into the app/agents directory
COPY . .

RUN pip3 install -r requirements.txt

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "synacc.py"]

# Sensible default arguments
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

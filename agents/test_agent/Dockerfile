# WireGrid Encoder Agent

# Use socs base image
FROM simonsobs/socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/test_agent/

# Copy this agent into the app/agents directory
COPY . .

# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "test_agent.py"]

# Sensible default arguments
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

#EXPOSE 50007/udp

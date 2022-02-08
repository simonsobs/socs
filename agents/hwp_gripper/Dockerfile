# SOCS HWP Gripper Agent
# socs Agent container for controlling and monitoring the status of the HWP grippers

# Use socs base image
FROM socs:latest

# Set the working directory to registry directory
WORKDIR /app/socs/agents/hwp_gripper/

## Copy this agent into the app/agents directory
COPY . .

# Run agent on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "gripper_agent.py"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

# Use socs base image
FROM socs:latest

RUN pip3 install pandas

# Set the working directory to registry directory
WORKDIR /app/socs/agents/magpie
COPY . .


# Run registry on container startup
ENTRYPOINT ["dumb-init", "python3", "-u", "magpie_agent.py"]

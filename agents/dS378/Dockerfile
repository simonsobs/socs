FROM simonsobs/socs:latest

# Set the working directory to registry directory
WORKDIR /app/agents/dS378/

# Copy this agent into the app/agents directory
COPY . /app/agents/dS378/

# Run registry on container startup
ENTRYPOINT ["python3", "-u", "./dS378_agent.py"]

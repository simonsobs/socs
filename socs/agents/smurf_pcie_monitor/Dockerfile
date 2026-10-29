FROM ghcr.io/slaclab/smurf-pcie:R3.3.3

# Install socs (pulls in ocs and all base dependencies)
RUN pip3 install --no-cache-dir socs

# Default entrypoint runs the agent
ENTRYPOINT ["python3", "-m", "socs.agents.smurf_pcie_monitor.agent"]

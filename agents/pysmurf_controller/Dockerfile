FROM simonsobs/sodetlib:v0.3.0

WORKDIR /app

# SOCS installation
RUN git clone https://github.com/simonsobs/socs.git \
    && pip3 install -r socs/requirements.txt \
    && pip3 install -e socs

ENV OCS_CONFIG_DIR /config


# Run registry on container startup
WORKDIR /app/socs/agents/pysmurf_controller

COPY . .
RUN pip3 install -r requirements.txt

ENTRYPOINT ["dumb-init", "python3", "-u", "pysmurf_controller.py"]

# Sensible defaults for setup with sisock
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

FROM simonsobs/sodetlib:v0.3.0-101-gccbc921

WORKDIR /app

# SOCS installation
RUN python3 -m pip install --src=/app/ -e git+https://github.com/simonsobs/socs.git#egg=socs

ENV OCS_CONFIG_DIR /config


# Run registry on container startup
WORKDIR /app/socs/agents/pysmurf_controller

COPY . .
RUN pip3 install -r requirements.txt

ENTRYPOINT ["dumb-init", "python3", "-u", "pysmurf_controller.py"]

# Sensible defaults for setup with sisock
CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

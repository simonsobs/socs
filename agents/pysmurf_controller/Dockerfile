FROM tidair/pysmurf:R2.1.0

# Installs Jupyter requirements
RUN pip3 install jupyter

WORKDIR /app

# Installs OCS requirements
#COPY requirements.txt .
#RUN pip3 install -r requirements.txt

# Where ocs config stuff will be mounted

WORKDIR /app/libs
RUN git clone https://github.com/simonsobs/ocs.git \
    && cd ocs \
    && pip3 install -r requirements.txt


ENV PYTHONPATH="/app/libs/ocs/:${PYTHONPATH}"
ENV PATH="/app/libs/ocs/bin:${PATH}"
ENV OCS_CONFIG_DIR /config
ENV JUPYTER_CONFIG_DIR /config/jupyter/

# Run registry on container startup
WORKDIR /app/pysmurf_controller
COPY . .
ENTRYPOINT ["python3", "-u", "pysmurf_controller.py"]

# Sensible defaults for setup with sisock
CMD ["--site-hub=ws://sisock-crossbar:8001/ws", \
     "--site-http=http://sisock-crossbar:8001/call"]

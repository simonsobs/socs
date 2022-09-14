# hwp_picoscope Agent image
FROM socs:latest

RUN apt update && apt install -y wget udev libusb-1.0-0

WORKDIR /make
# need to install old version, latest version doesn't work
RUN wget https://labs.picotech.com/debian/pool/main/libp/libpicoipp/libpicoipp_1.3.0-4r21_amd64.deb &&\
    wget https://labs.picotech.com/debian/pool/main/libp/libps3000a/libps3000a_2.1.0-6r570_amd64.deb &&\
    dpkg -i *deb

RUN git clone https://github.com/picotech/picosdk-python-wrappers.git
WORKDIR /make/picosdk-python-wrappers
RUN git switch -c 89003868b5bc52511ee57419f0afbfade25f1882
RUN python3 setup.py install

# Run agent on container startup
ENTRYPOINT ["dumb-init", "ocs-agent-cli"]

FROM socs:latest

WORKDIR /home/ocs/

# This line is to avoid warnings during the build.
ENV DEBIAN_FRONTEND="noninteractive"

# Galil installation information:
# -https://www.galil.com/sw/pub/all/doc/global/install/linux/ubuntu/
# -https://www.galil.com/sw/pub/all/doc/gclib/html/python.html
RUN apt-get update \
 && apt-get install -y apt-utils \
 && apt-get install -y wget libavahi-common-dev libavahi-client-dev libavahi-core-dev libcap-dev libdaemon-dev avahi-daemon \
 && wget https://www.galil.com/sw/pub/apt/all/galil-release_1_all.deb \
 && apt-get install -y ./galil-release_1_all.deb \
 && rm ./galil-release_1_all.deb \
 && apt-get update \
 && apt install -y gclib \
 && apt-get install -y --download-only gcapsd \
 && dpkg -x $(find / -name "gcapsd*.deb") /tmp/gcapsd/ \
 && mv -v /tmp/gcapsd/usr/sbin/gcapsd /usr/sbin/ \
 && rm -r /tmp/gcapsd/ \
 && cp /usr/share/gclib/src/wrappers/python/* . \
 && cp /usr/share/gclib/doc/examples/python/* . \
 && python3 -m pip install . \
 && python3 -c "import gclib; print(f'gclib location: {gclib.__file__}')"

COPY . .

ENTRYPOINT ["./wg-actuator-entrypoint.sh"]

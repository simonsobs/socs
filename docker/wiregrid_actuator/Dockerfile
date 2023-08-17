FROM socs:latest

WORKDIR /home/ocs/

RUN apt-get update \
 && apt-get install -y apt-utils \
 && apt-get install -y wget libavahi-common-dev libavahi-client-dev libavahi-core-dev libcap-dev libdaemon-dev avahi-daemon \
 && wget http://www.galil.com/sw/pub/all/crypto/GALIL-GPG-KEY-E29D0E4B.asc \
 && apt-key add GALIL-GPG-KEY-E29D0E4B.asc \
 && wget http://www.galil.com/sw/pub/ubuntu/20.04/galil.list \
 && cp galil.list /etc/apt/sources.list.d \
 && apt-get update \
 && apt-get install -y --download-only gclib \
 && dpkg -x $(find / -name "gclib*.deb") / \
 && apt-get install -y gclib \
 && apt-get install -y --download-only gcapsd \
 && dpkg -x $(find / -name "gcapsd*.deb") /tmp/gcapsd/ \
 && mv /tmp/gcapsd/usr/sbin/gcapsd /usr/sbin/ \
 && rm -r /tmp/gcapsd/ \
 && tar -xvf /usr/share/doc/gclib/src/gclib_python.tar.gz \
 && python3 setup.py install

COPY . .

ENTRYPOINT ["./wg-actuator-entrypoint.sh"]

FROM socs:latest

WORKDIR /app/socs/agents/wiregrid_actuator

RUN apt-get update \
 && apt-get install -y apt-utils \
 && apt-get install -y wget libavahi-common-dev libavahi-client-dev libavahi-core-dev libcap-dev libdaemon-dev avahi-daemon \
 && wget http://www.galil.com/sw/pub/all/crypto/GALIL-GPG-KEY-E29D0E4B.asc \
 && apt-key add GALIL-GPG-KEY-E29D0E4B.asc \
 && wget http://www.galil.com/sw/pub/ubuntu/20.04/galil.list \
 && cp galil.list /etc/apt/sources.list.d \
 && apt-get update \
 && apt-get install gclib \
 && python3 setup.py install

COPY . .

ENTRYPOINT ["./wg-actuator-entrypoint.sh"]

CMD ["--site-hub=ws://crossbar:8001/ws", \
     "--site-http=http://crossbar:8001/call"]

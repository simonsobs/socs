#!/bin/sh

/etc/init.d/dbus start
/etc/init.d/avahi-daemon start
/usr/sbin/gcapsd &
apt-get install gclib
python3 setup.py install
python3 -u wiregrid_actuator.py --site-hub=ws://crossbar:8001/ws --site-http=http://crossbar:8001/call &

## For interactive test ##
#python3 -u tmp_actuator.py --site-hub=ws://crossbar:8001/ws --site-http=http://crossbar:8001/call &
#while true; do
#	/bin/bash;
#done

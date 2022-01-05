#!/bin/sh

/etc/init.d/dbus start
/etc/init.d/avahi-daemon start
/usr/sbin/gcapsd &
apt-get install gclib
python3 setup.py install
# "$@" is all of the arguments on this script: wg-actuator-entrypoint.sh
dumb-init python3 -u wiregrid_actuator.py "$@"

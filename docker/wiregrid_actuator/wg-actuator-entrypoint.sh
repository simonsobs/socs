#!/bin/sh

/etc/init.d/dbus start
/etc/init.d/avahi-daemon start
/usr/sbin/gcapsd &

# "$@" is all of the arguments on this script: wg-actuator-entrypoint.sh
dumb-init ocs-agent-cli "$@"

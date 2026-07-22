#!/bin/sh

# remove unnecessary stale PID files for dbus / Avahi
rm -f /run/avahi-daemon/pid /var/run/avahi-daemon/pid
rm -f /run/dbus/pid /var/run/dbus/pid

/etc/init.d/dbus start
/etc/init.d/avahi-daemon start
/usr/sbin/gcapsd &

# "$@" is all of the arguments on this script: wg-actuator-entrypoint.sh
exec dumb-init ocs-agent-cli "$@"

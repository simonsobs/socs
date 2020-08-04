import sys
extraPYTHONPATH = '/home/polarbear/local/slowdaq'
sys.path.insert(0, extraPYTHONPATH)

import os
DAEMON_PATH = os.path.dirname(os.path.abspath(__file__))
DAEMONIZE = True
#DAEMONIZE = False

import T7Publisher

def main():
    t7 = T7Publisher.T7Publisher('LabjackT7', '192.168.2.10', 3141, daqid='192.168.2.153', scan_rate=2500., scan_port=['AIN0', 'AIN2'], scale=5)
    t7.stream()

def daemonize():
    pid = os.fork()
    if pid == 0:
        os.setsid()
        main()
    else:
        print "Started LabjackT7 daemon with PID %d"%pid

if __name__=='__main__':
    if DAEMONIZE:
        print 'Daemonize'
        daemonize()
    else:
        main()

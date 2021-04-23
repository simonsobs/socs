#import os
#os.environ['OCS_CONFIG_DIR'] = './'

from ocs.matched_client import MatchedClient
import time

class ACUClient(MatchedClient):
    def monitor_pos(self, period=.1):
        while True:
            try:
                time.sleep(period)
                ok, msg, sess = client.monitor.status()
                d = sess['data']
                for ax in ['Azimuth', 'Elevation']:
                    print(d[ax + ' current position'], end=' ')
                print()
            except KeyboardInterrupt:
                return
            except RuntimeError as e:
                print('Error: %s' % e)
                print('Waiting 5 seconds.')
                time.sleep(5)
                

client = ACUClient('acu1')

# e.g. client.control.start(mode='be_at', az_el=(150., 40))

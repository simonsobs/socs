import argparse
import subprocess
import time

import numpy as np
import txaio

txaio.use_twisted()

from ocs import ocs_agent, site_config


def get_sensors(shm_addr):
    """
    Runs a command on the shelf manager that returns a list of all
    of the avialable sensors to stdout. Uses subprocess module to
    read stdout and identify the ipmb address and sensor id for all
    sensors which are Threshold type as opposed to discrete type,
    which are alarms.
    Args:
        shm_addr (str):
            Address used to connect to shelf manager ex. root@192.168.1.2
    Returns:
        ipmbs (str list):
            List of Intelligent Platform Management Bus (IPMB) addresses
        sensids (str list):
            List of sensor identification names, same length as ipmbs list.
    """
    log = txaio.make_logger()

    # SSH to shelf manager
    cmd = ['ssh', f'{shm_addr}']
    # Send command to shelf manager
    cmd += ['clia', 'sensordata']
    # Intialize output data
    ipmbs = []
    sensids = []
    masksens = []
    check_sense = False

    # Send command to ssh and run command on shelf
    ssh = subprocess.Popen(cmd,
                           shell=False,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    # Readback shelfmanager standard out
    result = ssh.stdout.readlines()
    # Parse readback data line by line unless empty
    if result == []:
        error = ssh.stderr.readlines()
        log.error("ERROR: %s" % error)
    else:
        for r in result:
            if ': LUN' in r.decode('utf-8'):
                check_sense = True
                ipmbs.append(r.decode('utf-8').split(': LUN')[0])
                sname = r.decode('utf-8').split('(')[-1].split(')')[0]
                sensids.append(sname)
                continue
            if check_sense:
                if 'Threshold' in r.decode('utf-8'):
                    masksens.append(True)
                if 'Discrete' in r.decode('utf-8'):
                    masksens.append(False)
                check_sense = False
    ipmbs = np.asarray(ipmbs)
    sensids = np.asarray(sensids)
    masksens = np.asarray(masksens)
    return ipmbs[masksens], sensids[masksens]


def get_channel_names(ipmbs):
    """
    Converts ipmb addresses to human readable names based on the
    definitions of ipmb addresses in the ATCA manuals.
    Args:
        ipmbs (str list):
            List of Intelligent Platform Management Bus (IPMB) addresses
    Returns:
        chan_names (str list):
            List of human readable names for each IPMB address.
    """
    chan_names = np.zeros(len(ipmbs)).astype(str)
    for i, ipmb in enumerate(ipmbs):
        if ipmb == '20':
            chan_names[i] = 'shelf'
            continue
        if ipmb == 'fe':
            chan_names[i] = 'pwr_mgmt'
            continue
        slot = int('0x' + ipmb, 16) // 2 - 64
        if slot < 1:
            # Not exactly sure what this corresponds to...
            chan_names[i] = f"ipmb{ipmb}"
            continue
        if slot == 1:
            chan_names[i] = 'switch'
            continue
        chan_names[i] = f'slot{slot}'
    return chan_names


def get_data_dict(shm_addr, ipmbs, sensids, chan_names,
                  crate_id):
    """
    Given a list of ipmb addresses, sensor ids, and channel names,
    the shelf manager is queeried and the current sensor values for
    the provided list of sensors is read. The values are then
    output in a dictionary in the format needed to publish to
    influxdb.
    Args:
        shm_addr (str):
            Address used to connect to shelf manager ex. root@192.168.1.2
        ipmbs (str list):
            List of Intelligent Platform Management Bus (IPMB) addresses.
        sensids (str list):
            List of sensor identification names, same length as ipmbs list.
        chan_names (str list):
            List of human readable names for each IPMB address.
        crate_id (str):
            String to identify crate number in feed names, ex: crate_1
    Returns:
        data_dict (dict):
            Dict with structure, {data : value} collects the output
            of all of the sensors passed into the fuction. Ensures the
            keys match the influxdb feedname requirements
    """
    log = txaio.make_logger()

    data_dict = {}
    cmd = ['ssh', f'{shm_addr}', 'clia', 'sensordata']
    ssh = subprocess.Popen(cmd,
                           shell=False,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    result = ssh.stdout.readlines()
    if result == []:
        error = ssh.stderr.readlines()
        log.error("ERROR: %s" % error)
    else:
        for ipmb, sensid, chan_name in zip(ipmbs, sensids, chan_names):
            sense_chan = False
            for r in result:
                if ipmb in r.decode('utf-8'):
                    if sensid in r.decode('utf-8'):
                        sense_chan = True
                        continue
                if sense_chan:
                    if 'Processed data:' in r.decode('utf-8'):
                        sid = sensid.strip('"')
                        sid = sid.replace(" ", "_")
                        sid = sid.replace(":", "")
                        sid = sid.replace("+", "")
                        sid = sid.replace(".", "p")
                        sid = sid.replace("-", "_")
                        line = r.strip().decode("utf-8")
                        if line.split(':')[-1].split(' ')[0] == '':
                            val = float(line.split(':')[-1].split(' ')[1])
                        else:
                            val = float(line.split(':')[-1].split(' ')[0])
                        data_dict[f'{crate_id}_{chan_name}_{sid}'] = val
                        sense_chan = False
    return data_dict


class SmurfCrateMonitor:
    def __init__(self, agent, crate_id, shm_addr):
        self.agent = agent
        self.log = agent.log
        self.shm_addr = shm_addr
        self.crate_id = crate_id
        # Register feed
        agg_params = {
            'frame_length': 10 * 60
        }
        self.log.info('registering')
        self.agent.register_feed('smurf_sensors',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0.)

    def _init_data_stream(self, shm_addr):
        """Wrapper for get_sensors and get_channel_names which generates the
        list of sensors to use in datastreaming.

        Args:
            shm_addr (str): Address used to connect to shelf manager ex.
                root@192.168.1.2
        Return:
            ipmbs (str list): List of Intelligent Platform Management Bus
                (IPMB) addresses.
            sensids (str list): List of sensor identification names, same
                length as ipmbs list.
            chan_names (str list): List of human readable names for each IPMB
                address.
        """
        ipmbs, sensids = get_sensors(shm_addr)
        chan_names = get_channel_names(ipmbs)
        return ipmbs, sensids, chan_names

    def init_crate(self, session, params=None):
        """init_crate()

        **Task** - Initialize connection to the SMuRF crate.

        Run at the startup of the docker to check that you can
        successfully ssh to the crate and run a command. If it runs
        successfully then you should see the home directory of the shelf
        manager printed to the docker logs and the data acquisition process to
        start, if not you will see an error in the logs and acquistion won't
        start.

        """
        self.log.info(self.shm_addr)
        cmd = ['ssh', f'{self.shm_addr}', 'pwd']
        self.log.info("command run: {c}", c=cmd)
        ssh = subprocess.Popen(cmd,
                               shell=False,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        result = ssh.stdout.readlines()
        self.log.info(result[0])
        if result == []:
            error = ssh.stderr.readlines()
            self.log.error(f"ERROR: {error}")
            return False, 'Crate failed to initialize'
        if result[0].decode("utf-8") == '/etc/home/root\n':
            self.log.info('Successfully ssh-d into shelf')
            self.agent.start('acq')
            return True, 'Crate Initialized'

    def acq(self, session, params=None):
        """acq()

        **Process** - Start acquiring data.

        Hardcoded for one data point every 30 seconds because we intend for
        this to be very low rate data.

        """
        self.log.info('Started acquisition')
        shm_addr = self.shm_addr
        ipmbs, sensids, chan_names = self._init_data_stream(shm_addr=shm_addr)
        self.log.info('Got sensor names')
        self.take_data = True
        while self.take_data:
            for _ in range(30):
                if not self.take_data:
                    break
                time.sleep(1)
            datadict = get_data_dict(shm_addr=self.shm_addr,
                                     ipmbs=ipmbs,
                                     sensids=sensids,
                                     chan_names=chan_names,
                                     crate_id=self.crate_id)
            data = {
                'timestamp': time.time(),
                'block_name': f'smurf_{self.crate_id}',
                'data': datadict
            }
            self.agent.publish_to_feed('smurf_sensors', data)
        return True, 'Acquisition exited cleanly'

    def _stop_acq(self, session, params=None):
        """
        Stops acquiring data if the dpcler os stopped.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()
    # Add options specific to this agent.
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument('--shm-addr',
                        help='Shelf manager addres i.e. root@192.168.1.2')
    pgroup.add_argument('--crate-id',
                        help='Crate id used for block_name')
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='CrateAgent',
                                  parser=parser,
                                  args=args)
    startup = True
    agent, runner = ocs_agent.init_site_agent(args)
    shm_addr = args.shm_addr
    crate_id = args.crate_id

    smurfcrate = SmurfCrateMonitor(agent, crate_id, shm_addr)

    agent.register_task('init_crate', smurfcrate.init_crate,
                        startup=startup)
    agent.register_process('acq', smurfcrate.acq,
                           smurfcrate._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()

import time
import os
import socket
import txaio
import argparse
import numpy as np

from motor_driver import MotControl

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock, Pacemaker

class MotorControlAgent:
    def __init__(self, agent, motor1_Ip, motor1_Port, motor1_isLin, motor2_Ip, motor2_Port, motor2_isLin,  mRes, samp=2):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        # Pass these through site config
        self.motor1_Ip = motor1_Ip
        self.motor1_Port = motor1_Port
        self.motor1_isLin = motor1_isLin
        self.motor2_Ip = motor2_Ip
        self.motor2_Port = motor2_Port
        self.motor2_isLin = motor2_isLin
        self.mRes = mRes
        self.sampling_frequency = samp

        self.motor = None
        self.initialized = False
        self.take_data = False
        self.move_status = False

        ### register the position feeds
        agg_params = {
            'frame_length' : 10*60, #[sec] 
        }

        self.agent.register_feed('positions',
                                 record = True,
                                 agg_params = agg_params,
                                 buffer_time = 0)

    def connect_motor(self, session, params=None):
        """ Task to connect to the motors, either one or both """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.motor = MotControl(motor1_Ip=self.motor1_Ip, motor1_Port=self.motor1_Port, motor1_isLin=self.motor1_isLin, motor2_Ip=self.motor2_Ip, motor2_Port=self.motor2_Port, motor2_isLin=self.motor2_isLin, mRes = self.mRes)
            except socket.timeout as e:
                self.log.error("Motor timed out during connect")
                return False, "Timeout"

        self.initialized = True

        return True, "Initialized motor."

    def moveAxisToPosition(self, session, params=None):

        linStage = params.get('linStage',True)

        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.moveAxisToPosition(params['motor'],params['pos'],params['posIsInches'],linStage)
            else:
                return False, "Could not acquire lock"

        return True, "Moved motor {} to {}".format(params['motor'],params['pos'])

    def moveAxisByLength(self, session, params=None):

        linStage = params.get('linStage',True)
        
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.moveAxisByLength(params['motor'],params['pos'],params['posIsInches'],linStage)
            else:
                return False, "Could not acquire lock"

        return True, "Moved motor {} by {}".format(params['motor'],params['pos'])

    def setVelocity(self, session, params=None):

        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.setVelocity(params['motor'],params['velocity'])
            else:
                return False, "Could not acquire lock"

        return True, "Set velocity of motor {} to {}".format(params['motor'],params['velocity'])

    def setAcceleration(self, session, params=None):

        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.setAcceleration(params['motor'],params['accel'])
            else:
                return False, "Could not acquire lock"

        return True, "Set acceleration of motor {} to {}".format(params['motor'],params['accel'])

    def startJogging(self, session, params=None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.startJogging(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Started jogging motor {}".format(params['motor'])

    def stopJogging(self, session, params=None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.stopJogging(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Stopped jogging motor {}".format(params['motor'])

    def seekHomeLinearStage(self, session, params=None):

        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.seekHomeLinearStage(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Moving motor {} to home".format(params['motor'])

    def setZero(self, session, params=None):

        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.setZero(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Zeroing motor {} position".format(params['motor'])

    def runPositions(self, session, params=None):

        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.runPositions(params['posData'],params['motor'],params['posIsInches'])
            else:
                return False, "Could not acquire lock"

        return True, "Moving stage to {}".format(params['posData'])

    def startRotation(self, session, params=None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.startRotation(params['motor'],params['velocity'],params['accel'])
            else:
                return False, "Could not acquire lock"

        return True, "Started rotating motor at velocity {} and acceleration {}".format(params['velocity'],params['accel'])

    def stopRotation(self, session, params=None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.stopRotation(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Stopped rotating motor"

    def closeConnection(self, session, params=None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.closeConnection(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Closed connection to motor {}".format(params['motor'])

    def blockWhileMoving(self, session, params=None):

        verbose = params.get('verbose',False)

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.blockWhileMoving(params['motor'],params['updatePeriod'],verbose)
            else:
                return False, "Could not acquire lock"

        return True, "Motor {} stopped moving".format(params['motor'])

    def killAllCommands(self, session, params=None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.killAllCommands(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Killing all active commands on motor {}".format(params['motor'])
    
    def setEncoderValue(self, session, params=None):

        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                ePositions = self.motor.setEncoderValue(params['motor'],params['value'])
            else:
                return False, "Could not acquire lock"

        return True, "Setting encoder position to {}".format(ePositions)

    def getEncoderValue(self, session, params = None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                ePositions = self.motor.retrieveEncoderInfo(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, ("Current encoder positions: {}".format(ePositions),ePositions)

    def getPositions(self, session, params = None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                if params['inches']:
                    positions = self.motor.getPositionInInches(params['motor'])
                elif not params['inches']:
                    positions = self.motor.getPosition(params['motor'])
                else: 
                    return False, "Invalid choice for inches parameter, must be boolean"
            else:
                return False, "Could not acquire lock"

        return True, "Current motor positions: {}".format(positions)

    def posWhileMoving(self, session, params = None):

        inches = params.get('inches',True)

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                iPositions = self.motor.getImmediatePosition(params['motor'],inches)
            else:
                return False, "Could not acquire lock"

        return True, "Current motor positions: {}".format(iPositions)

    def isMoving(self, session, params = None):

        verbose = params.get('verbose',True)

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.move_status = self.motor.isMoving(params['motor'],verbose)
            else:
                return False, "Could not acquire lock"

        if self.move_status:
            return True, ("Motors are moving.",self.move_status)
        else:
            return True, ("Motors are not moving.",self.move_status)

    def resetAlarms(self, session, params = None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.resetAlarms(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Alarms reset for motor {}".format(params['motor'])

    def homeWithLimits(self, session, params = None):

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.motor.homeWithLimits(params['motor'])
            else:
                return False, "Could not acquire lock"

        return True, "Zeroed stages using limit switches"

    def start_acq(self, session, params=None):

        if params is None:
            params = {}

        motor = params.get('motor',3)
        verbose = params.get('verbose',False)

        f_sample = params.get('sampling_frequency', self.sampling_frequency)
        pm = Pacemaker(f_sample, quantize=True)

        if not self.initialized or self.motor is None:
            raise Exception("Connection to motors is not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
            
            self.log.info(f"Starting data acquisition for stages at {f_sample} Hz")
            session.set_status('running')
            self.take_data = True
            last_release = time.time()

            mList = self.motor.genMotorList(motor)
            # Check that each motor in the list is valid
            for mot in mList:
                if not mot:
                    print("Specified motor is invalid, removing from list")
                    mList.remove(mot)
                    continue

            while self.take_data:
                if time.time()-last_release > 1.:
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False, "could not re-acquire lock"
                    last_release = time.time()
                pm.sleep()

                self.move_status = self.motor.isMoving(motor,verbose)

                # Using list of initialized motors generated at the start of acq
                data = {'timestamp':time.time(), 'block_name':'positions','data':{}}

                # get immediate position for motor, one at a time
                # this makes sure that no matter how many motors 
                # are initialized, it appends the right number
                for i,mot in enumerate(mList):
                    mot_id = mot.propDict['motor']
                    if self.move_status:
                        pos = self.motor.getImmediatePosition(motor=mot_id)
                        data['data'][f'motor{mot_id}_stepper'] = pos[0]
                        data['data'][f'motor{mot_id}_encoder'] = -1


                    if not self.move_status:
                        pos = self.motor.getImmediatePosition(motor=i+1)
                        data['data'][f'motor{mot_id}_stepper'] = pos[0]
                        ePos = self.motor.retrieveEncoderInfo(motor=i+1)
                        data['data'][f'motor{mot_id}_encoder'] = ePos[0]

                self.agent.publish_to_feed('positions',data)

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'Requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'



        
    
def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--motor1_Ip', help="MOXA IP address",type=str)
    pgroup.add_argument('--motor1_Port', help="MOXA port number for motor 1",type=int)
    pgroup.add_argument('--motor1_isLin', action='store_true',
                        help="Whether or not motor 1 is connected to a linear stage")
    pgroup.add_argument('--motor2_Ip', help="MOXA IP address",type=str)
    pgroup.add_argument('--motor2_Port', help="MOXA port number for motor 1",type=int)
    pgroup.add_argument('--motor2_isLin', action='store_true',
                        help="Whether or not motor 1 is connected to a linear stage")
    pgroup.add_argument('--mRes', help="Manually enter microstep resolution",action='store_true')
    pgroup.add_argument('--sampling_frequency', help="Frequency to sample at for data acq",type=float)
    
    return parser 

if __name__ == '__main__':
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    # Parse comand line.
    parser = make_parser()
    args = site_config.parse_args(agent_class='MotorControlAgent',parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    m = MotorControlAgent(agent, args.motor1_Ip, args.motor1_Port, args.motor1_isLin, args.motor2_Ip, args.motor2_Port, args.motor2_isLin, args.mRes, args.sampling_frequency)

    agent.register_task('connect', m.connect_motor)
    agent.register_task('move_to_position', m.moveAxisToPosition)
    agent.register_task('move_by_length', m.moveAxisByLength)
    agent.register_task('set_velocity', m.setVelocity)
    agent.register_task('set_accel', m.setAcceleration)
    agent.register_task('start_jog', m.startJogging)
    agent.register_task('stop_jog', m.stopJogging)
    agent.register_task('seek_home', m.seekHomeLinearStage)
    agent.register_task('set_zero', m.setZero)
    agent.register_task('run_positions', m.runPositions)
    agent.register_task('start_rotation', m.startRotation)
    agent.register_task('stop_rotation', m.stopRotation)
    agent.register_task('close_connect', m.closeConnection)
    agent.register_task('block_while_moving', m.blockWhileMoving)
    agent.register_task('kill_all', m.killAllCommands)
    agent.register_task('set_encoder', m.setEncoderValue)
    agent.register_task('get_encoder', m.getEncoderValue)
    agent.register_task('get_position', m.getPositions)
    agent.register_task('is_moving', m.isMoving)
    agent.register_task('get_imm_position', m.posWhileMoving)
    agent.register_task('reset_alarm', m.resetAlarms)
    agent.register_task('home_with_limits', m.homeWithLimits)

    agent.register_process('acq', m.start_acq, m.stop_acq)


    runner.run(agent, auto_reconnect=True)

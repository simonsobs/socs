import time
import os
import socket
import txaio
import argparse
import numpy as np

from sat1_motors_driver import MotControl

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock, Pacemaker


class SAT1MotorsAgent:
    """
    Agent for connecting to the SAT1 XY Stages. Differs from LATRt agent in that motors/controllers are seen as arguments.
    Motor1 can be the X axis OR the Y axis, same with Motor2. Depends on setup (ip address + port). 
    
    Args: 
        motor1_Ip (str) -- the IP address associated with Motor1
        motor1_Port (int) -- the port address associated with Motor1
        motor1_isLin (bool) -- Boolean that determines if Motor1 is a linear motor.
        motor2_Ip (str) -- the IP address associated with Motor2
        motor2_Port (int) -- the port address associated with Motor2
        motor2_isLin (bool) -- Boolean that determines if Motor2 is a linear motor.
        mode: 'acq': Start data acquisition on initialize
        mRes (bool) -- True if manual resolution, False if default (res=8) ???
        samp: default sampling frequency in Hz
    """
    
    def __init__(self, agent, motor1_Ip, motor1_Port, motor1_isLin, motor2_Ip, motor2_Port, motor2_isLin, mRes, mode=None, samp=2):

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
        self.move_status = False

        self.motors = None
        self.initialized = False
        self.take_data = False
        self.move_status = False
        
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        
        if mode == 'acq':
            self.auto_acq = True
        else:
            self.auto_acq = False
        self.sampling_frequency = float(samp)

        ### register the position feeds
        agg_params = {
            'frame_length' : 10*60, #[sec] 
        }

        self.agent.register_feed('positions',
                                 record = True,
                                 agg_params = agg_params,
                                 buffer_time = 0)
        
    def init_motors_task(self, session, params=None):
        """init_xy_stage_task(params=None)
        Task to connect to the motors, either one or both

        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.
        """

        if params is None:
            params = {}
        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired Connecting to Stages")
            self.motors = MotControl(motor1_Ip=self.motor1_Ip, motor1_Port=self.motor1_Port, motor1_isLin=self.motor1_isLin, motor2_Ip=self.motor2_Ip, motor2_Port=self.motor2_Port, motor2_isLin=self.motor2_isLin, mRes = self.mRes)            
            
        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq')
        return True, 'Motor(s) Initialized.'    

    def moveAxisToPosition(self, session, params=None):
        """
        Move the axis to the given absolute position in counts or inches.
        NOTE: If moving multiple axes, function will assume linStage value for all axes.
        Parameters:
            params: {'motor': int, 'pos': float, 'posIsInches': bool, 'linStage': bool}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
            pos: float. The desired position in counts or in inches, positive indicates away from the motor (default 0)
            posIsInches: bool. True if pos was specified in inches, False if in counts (default False)
            linStage: bool. True if the specified motor is for the linear stage, False if not (default True)    
        """

        linStage = params.get('linStage',True)
        motor = params.get('motor', 1)
        posIsInches = params.get('posIsInches', False)
        pos = params.get('pos', 0)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(1, job=f'moveAxisToPosition_motor{motor}') as acquired:
            if not acquired:
                    self.log.warn(f"Could not move motor{motor} because lock held by {self.lock.job}")
                    return False, "Could not acquire lock"
            self.motors.moveAxisToPosition(motor, pos, posIsInches, linStage)

        return True, "Moved motor {} to {}".format(motor, pos)

    def moveAxisByLength(self, session, params=None):
        """
        Move the axis relative to the current position by the specified number of counts or inches.      
        NOTE: If moving multiple axes, function will assume linStage value for all axes.
        Parameters:
            params: {'motor': int, 'pos': float, 'posIsInches': bool, 'linStage': bool}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
            pos: float. The desired position in counts or in inches, positive indicates away from the motor (default 0)
            posIsInches: bool. True if pos was specified in inches, False if in counts (default False)
            linStage: bool. True if the specified motor is for the linear stage, False if not (default True)    
        """

        linStage = params.get('linStage',True)
        motor = params.get('motor', 1)
        pos = params.get('pos', 0)
        posIsInches = params.get('posIsInches', False)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(1, job=f'moveAxisByLength_motor{motor}') as acquired:
            if not acquired:
                    self.log.warn(f"Could not move motor{motor} because lock held by {self.lock.job}")
                    return False, "Could not acquire lock"
            self.motors.moveAxisByLength(motor, pos, posIsInches, linStage)
                
        return True, "Moved motor {} by {}".format(motor, pos)
    
    ###################################################################    
    # I created an alternative move_motors function below. 
    # Perhaps this is more useful? Will check with Joe...
    ###################################################################    
    def move_motors(self, session, params):
        """
        Moves up to 2 motors. Specified by the params['pos'] value. First element controls motor1, second element
        controls motor2. If the element is 0, then does NOT move that motor.
        
        params: 
        
            params: {'motor': int, 'lin1'}
        
        
            dict: { 'lin1': (bool,bool), 'move_method': str, 'pos': (float>=0,float>=0), 'pos_is_inches': bool}  
            'lin_stages' : Determines if motor1 or motor2 controls a linear stage. 
            'move_method' : 'by_position' or 'by_length'. Determines how to move the motor(s)
            'pos' : Determines how far to move motor1 (1st element) and motor2 (2nd element). 
                If a value is 0, then don't move that motor.
            'pos_is_inches' : Determines to convert steps to inches or not for both movement methods and motors.
            
        """
        
        # Set variables and handle easy errors
        lin_stages = params.get('lin_stages', (True, True))
        if not isinstance(lin_stages, tuple):
            raise Exception("params['lin_stages'] must be a tuple of floats!")
        move_method = params.get('move_method', 'by_position')
        pos = params.get('pos', (0,0))
        if not isinstance(pos, tuple):
            raise Exception("params['pos'] must be a tuple of floats!")        
        pos_is_inches = params.get('pos_is_inches', False)

        # move both motors ONE AT A TIME, while checking lock files.
        # NOTE: I'm essentially getting rid of the 'MOTOR3==ALL' argument. Just specify via params['pos'] values.
        for idx,position in enumerate(pos):
            with self.lock.acquire_timeout(timeout=3, job=f'move_motor{idx+1}') as acquired:
                if not acquired:
                    self.log.warn(f"Could not start motor {idx+1} move because lock held by {self.lock.job}")
                    return False
                if position == 0:
                    print(f'not moving motor{idx+1} because position = 0')
                    continue
                if 'move_method' == 'by_length':
                    self.motors.moveAxisByLength(idx+1,pos[idx],pos_is_inches,lin_stages[idx])
                elif 'move_method' == 'by_position':
                    self.motors.moveAxisToPosition(idx+1,pos[idx],pos_is_inches,lin_stages[idx])
                else:
                    raise Exception("{params['move_method']} is not a valid movement method!")
                        
            time.sleep(1)
            while True:
                ## data acquisition updates the moving field if it is running
                if not self.take_data:
                    with self.lock.acquire_timeout(timeout=3, job=f'move_motor{idx+1}') as acquired:
                        if not acquired:
                            self.log.warn(f"Could not check because lock held by {self.lock.job}")
                            return False, "Could not acquire lock"
                        self.move_status = self.motors.isMoving(idx+1)

                if not self.move_status:
                    break                    
            
        return True, "Move Complete"
    ###################################################################
    #                      move_motors END
    ###################################################################    

    def setVelocity(self, session, params=None):
        """
        Set velocity of motors driving stages
        params: {'motor': int, 'velocity': float}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 3)
        velocity: [0.25,50]. Sets velocity of motor in revolutions/second (default 12.0)
        """
        
        motor = params.get('motor',3)
        velocity = params.get('velocity', 12.0)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(timeout=1, job=f'setVelocity{motor}') as acquired:
            if not acquired: 
                self.log.warn(f"Could not setVelocity because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.setVelocity(motor, velocity)
        
        return True, "Set velocity of motor {} to {}".format(motor, velocity)

    def setAcceleration(self, session, params=None):
        """
        Set acceleration of motors driving stages
        params: {'motor': int, 'accel': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 3)
        accel: [1,3000]. Sets acceleration in revolutions/second/second (default 1.0)
        """
        
        motor = params.get('motor', 3)
        accel = params.get('accel', 1.0)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(timeout=1, job=f'setAcceleration_motor{motor}') as acquired:
            if not acquired: 
                self.log.warn(f"Could not setAcceleration because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.setAcceleration(motor, accel)
            
        return True, "Set acceleration of motor {} to {}".format(motor, accel)
    
    def startJogging(self, session, params=None):
        """
        Jogs the motor(s) set by params
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"startJogging_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not startJogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            self.motors.startJogging(motor)

        return True, "Started jogging motor {}".format(motor)

    def stopJogging(self, session, params=None):
        """
        Stops the jogging of motor(s) set by params
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"stopJogging_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not stopJogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'                
            self.motors.stopJogging(motor)

        return True, "Stopped jogging motor {}".format(motor)

    def seekHomeLinearStage(self, session, params=None):
        """
        Move the linear stage to its home position (using the home limit switch).
        Parameters:
            parms: {'motor': int, 'isLin': bool}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        
        motor = params.get('motor',1)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(timeout=1, job=f'seekHomeLinearStage_motor{motor}') as acquired:
            if not acquired: 
                self.log.warn(f"Could not seekHomeLinearStage because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.seekHomeLinearStage(motor)
            
        return True, "Moving motor {} to home".format(motor)
    
    def setZero(self, session, params=None):
        """
        Sets the zero position (AKA home) for motor(s) specified in params
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """

        motor = params.get('motor',1)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1, job=f"setZero_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not setZero because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'                
            self.motors.setZero(motor)

        return True, "Zeroing motor {} position".format(motor)

    def runPositions(self, session, params=None):
        """
        Runs a tab-delimited list of entries as positions from a text file.  For motor=3, the first column
        must be the x-data, and the second column the y-data.  Each position will be attained.
        xPosition and yPosition will be specified as in the file.        
        params: {'motor': int, 'posData': .tsv file, 'posIsInches': bool}
        motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        posData: tab-delimited list of entries. first column is x-data, second column is y-data.
        posIsInches: Boolean. (default True)
        """
        
        motor = params.get('motor', 1)
        posIsInches = params.get('posIsInches', True)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(1, job=f"runPositions_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not runPositions because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'                                    
            self.motors.runPositions(params['posData'], motor, posIsInches)
            
        return True, "Moving stage to {}".format(params['posData'])

    def startRotation(self, session, params=None):
        """
        Start rotating motor of polarizer. NOTE: Give acceleration and velocity values as arguments here.
        params: {'motor': int, 'velocity': float, 'accel': float}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        velocity: float. [0.25,50] The rotation velocity in revolutions/second (default 12.0)
        accel: float. [1,3000] -- The acceleration in revolutions/second/second (default 1.0)
        """
        
        motor = params.get('motor', 1)
        velocity = params.get('velocity', 12.0)
        accel = params.get('accel', 1.0)
        with self.lock.acquire_timeout(1, job=f"startRotation_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f"Could not startRotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.startRotation(motor, velocity, accel)
            
        return True, "Started rotating motor at velocity {} and acceleration {}".format(velocity, accel)

    def stopRotation(self, session, params=None):
        """
        Stop rotating motor of polarizer.
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"stopRotation_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f"Could not stopRotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.stopRotation(motor)

        return True, "Stopped rotating motor"
   
    def closeConnection(self, session, params=None):
        """
        Close connection to specific motor
        
        ########################################
        still need to think about this!
        ########################################
        
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 3)
        """
        
        motor = params.get('motor', 3) 
        with self.lock.acquire_timeout(1, job=f"closeConnection_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not close connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"                
            self.motors.closeConnection(motor)

        return True, "Closed connection to motor {}".format(motor)

    def blockWhileMoving(self, session, params=None):
        """
        Block until the specified axes/motor have stop moving.  Checks each axis every updatePeriod seconds.
        params: {'motor': int, 'updatePeriod': float, 'verbose': bool}
        motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        updatePeriod: float. Time after which to check each motor in seconds (default .1)
        verbose: bool. Prints output from motor requests if True (default False)
        """

        motor = params.get('motors', 1)
        updatePeriod = params.get('updatePeriod', .1)
        verbose = params.get('verbose',False)
        with self.lock.acquire_timeout(1, job=f"blockWhileMoving_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not blockWhileMoving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"                                
            self.motors.blockWhileMoving(motor, updatePeriod, verbose)

        return True, "Motor {} stopped moving".format(motor)

    def killAllCommands(self, session, params=None):
        """
        Stops all active commands on the device. Does not interact with lock file...
        params: {'motor': int}
        motor: 1,2,3. Determines which motor, 3 is for all motors. (default 3)
        """
        
        motor = params.get('motor', 3)
        with self.lock.acquire_timeout(1, job=f"killAllCommands_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not killAllCommands because lock held by {self.lock.job}')
                return False, "Could not acquire lock"                                
            self.motors.killAllCommands(motor)
    
        return True, "Killing all active commands on motor {}".format(motor)
    
    def setEncoderValue(self, session, params=None):
        """
        Set the encoder values in order to keep track of absolute position
        Parameters:
            params: {'motor': int, 'value': float}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
            value: Sets encoder value. (default 0)
        """

        motor = params.get('motor', 1)
        value = params.get('value', 0)
        self.move_status = self.motors.isMoving(motor)
        if self.move_status:
            return False, "Motors are already moving."
        
        with self.lock.acquire_timeout(1, job=f"setEncoderValue_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not setEncoderValue because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'                                    
            ePositions = self.motors.setEncoderValue(motor, value)

        return True, "Setting encoder position to {}".format(ePositions)

    def getEncoderValue(self, session, params = None):
        """
        Retrieve all motor step counts to verify movement.
        Parameters:
            params: {'motor': int}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 3)
        """
        
        motor = params.get('motor', 3)
        with self.lock.acquire_timeout(1, job=f"getEncoderInfo_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not getEncoderInfo because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'                                    
            ePositions = self.motors.retrieveEncoderInfo(motor)

        return True, ("Current encoder positions: {}".format(ePositions),ePositions)    
    
    def getPositions(self, session, params = None):
        """
        Get the position of the motor in counts, relative to the set zero point (or starting point/home).
        
        Parameters:
            params: {'motor': int, 'inches': bool}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
            inches: bool. Whether to return positions in inches or not. (default True)
        Returns:
            positions (list) -- the positions of the specified motors
        """
        
        motor = params.get('motor', 1)
        inches = params.get('inches', True)
        with self.lock.acquire_timeout(1, job=f"getPositions_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not getPositions because lock held by {self.lock.job}')
                return False, "Could not acquire lock"                                
            if inches:
                positions = self.motors.getPositionInInches(motor)
            elif not inches:
                positions = self.motors.getPosition(motor)
            else: 
                return False, "Invalid choice for inches parameter, must be boolean"

        return True, "Current motor positions: {}".format(positions)

    def posWhileMoving(self, session, params = None):
        """
        Get the position of the motor while it is currently in motion. An estimate based on the 
        calculated trajectory of the movement, relative to the zero point.
        
        Parameters:
            params: {'motor': int, 'inches': bool}
            motor: 1,2,3. Determines which motor, 3 is for all motors. (default 1)
            inches: bool. Whether to return positions in inches or not. (default True)
        Returns:
            positions (list) -- the positions of the specified motors
        """
        
        inches = params.get('inches',True)
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"posWhileMoving_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f'Could not posWhileMoving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"                                
            iPositions = self.motors.getImmediatePosition(motor,inches)

        return True, "Current motor positions: {}".format(iPositions)

    # NOTE: I do not understand point of this function really. 
    # perhaps just for the user to query movement status on a whim?
    def isMoving(self, session, params = None):
        """
        Checks if motors are moving OR if limit switches are tripped.
        
        ########################################
        still need to think about this!
        ########################################
        
        params{'motor' : int, 'verbose' : bool}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        verbose = params.get('verbose',True)
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"isMoving_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f"Could not check because lock held by {self.lock.job}")
                return False
            self.move_status = self.motors.isMoving(motor,verbose)

        if self.move_status:
            return True, ("Motors are moving.",self.move_status)
        else:
            return True, ("Motors are not moving.",self.move_status)

    def resetAlarms(self, session, params = None):
        """
        Resets alarm codes present. Only advised if you have checked what the alarm is first!
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"resetAlarms_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f"Could not resetAlarms because lock held by {self.lock.job}")
                return False
            self.motors.resetAlarms(motor)

        return True, "Alarms reset for motor {}".format(motor)

    def homeWithLimits(self, session, params = None):
        """
        Moves stages to home based on location from limits. One inch from the limit switch.
        params: {'motor': int}
        motor : 1,2,3. Determines which motor, 3 is for all motors. (default 1)
        """
        
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"homeWithLimits_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(f"Could not move motor{motor} to home because lock held by {self.lock.job}")
                return False
            self.motors.homeWithLimits(motor)

        return True, "Zeroed stages using limit switches"

    def start_acq(self, session, params=None):
        """
        Start acquisition of data.
        params: {'motor': int, 'verbose': bool, sampling_frequency': float}
        motor: 1,2,3. Determines which motor, 3 is for all motors. (default 3)
        verbose: bool. Prints output from motor requests if True (default False)
        sampling_frequency: float, sampling rate in Hz (default 2)
        
        ########################################
        still need to think about this!
        ########################################
        """
        if params is None:
            params = {}

        motor = params.get('motor',3)
        verbose = params.get('verbose',False)
        f_sample = params.get('sampling_frequency', self.sampling_frequency)
        pm = Pacemaker(f_sample, quantize=True)

        if not self.initialized or self.motors is None:
            raise Exception("Connection to motors is not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
            self.log.info(f"Starting data acquisition for stages at {f_sample} Hz")
            session.set_status('running')
            self.take_data = True
            last_release = time.time()

# ************CODE BELOW DOES 'NOTHING', NOTHING WE WANT ANYWAYS*****************************

#             mList = self.motors.genMotorList(motor)
#             # Check that each motor in the list is valid
#             for mot in mList:
#                 if not mot:
#                     print("Specified motor is invalid, removing from list")
#                     mList.remove(mot)
#                     continue

# **********************************END******************************************************

            while self.take_data:
                if time.time()-last_release > 1.:
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False, "could not re-acquire lock"
                    last_release = time.time()
                pm.sleep()
                
                # Using list of initialized motors generated at the start of acq
                data = {'timestamp':time.time(), 'block_name':'positions','data':{}}

                # get immediate position for motor, one at a time
                # this makes sure that no matter how many motors 
                # are initialized, it appends the right number
                mList = self.motors.genMotorList(motor)
                
#                 Note: if motor is moving, can't retrieve encoder info. But can always get immediate position!
                for mot in mList:
                    mot_id = mot.propDict['motor']
                    try:
                        self.log.warn(f"getting position/move status of motor{mot_id}")
                        self.move_status = self.motors.isMoving(mot_id,verbose)
                        pos = self.motors.getImmediatePosition(motor=mot_id)
                        if self.move_status:
                            data['data'][f'motor{mot_id}_encoder'] = -1
                        else:
                            ePos = self.motors.retrieveEncoderInfo(motor=mot_id)
                            data['data'][f'motor{mot_id}_encoder'] = ePos[0]
                        data['data'][f'motor{mot_id}_stepper'] = pos[0]
                        data['data'][f'motor{mot_id}_connection'] = True

                    except Exception as e:
                        self.log.warn(f'error: {e}')
                        self.log.warn(f"could not get position/move status of motor{mot_id}")
                        data['data'][f'motor{mot_id}_stepper'] = -10000
                        data['data'][f'motor{mot_id}_encoder'] = -10000
                        data['data'][f'motor{mot_id}_connection'] = False
                        continue

                self.agent.publish_to_feed('positions',data)        
            
        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stop data acquisition.
        params: {}
        
        ########################################
        still need to think about this!
        ########################################
        """

        if self.take_data:
            self.take_data = False
            return True, 'Requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'
   
    
def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """

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
                        help="Whether or not motor 2 is connected to a linear stage")
    pgroup.add_argument('--mRes', help="Manually enter microstep resolution",action='store_true')
    pgroup.add_argument('--sampling_frequency', help="Frequency to sample at for data acq",type=float)
    pgroup.add_argument('--mode',help="puts mode into auto acquisition or not...",type=str)

    
    return parser 
    
if __name__ == '__main__':
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    # Parse comand line.
    parser = make_parser()
    args = site_config.parse_args(agent_class='SAT1MotorsAgent',parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    m = SAT1MotorsAgent(agent, args.motor1_Ip, args.motor1_Port, args.motor1_isLin, args.motor2_Ip, args.motor2_Port, args.motor2_isLin, args.mRes, args.mode, args.sampling_frequency)

    agent.register_task('init_motors', m.init_motors_task)
    agent.register_task('move_to_position', m.moveAxisToPosition)
    agent.register_task('move_by_length', m.moveAxisByLength)
    agent.register_task('move_motors', m.move_motors)
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

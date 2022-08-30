.. highlight:: rst

.. _appmotion_motor:

============================
Applied Motion Motors Agent
============================

This agent is used to communicate with NEMA motors, particularly the beam-
mapper motors.

.. argparse::
   :filename: ../agents/appmotion_motor/appmotion_motors_agent.py
   :func: make_parser
   :prog: python3 appmotion_motors_agent.py


Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'appMotionMotorsAgent',
         'instance-id': 'beammap-motors',
         'manage': 'docker',
         'arguments':[
           ['--motor1-ip', '192.168.0.188'],
           ['--motor1-port', '4001'],
           ['--motor1-is-lin'],
           ['--motor2-ip', '192.168.0.188'],
           ['--motor2-port', '4002'],
           #['--motor2-is-lin'],
           ['--sampling-frequency','2'],
           ['--mode', 'acq'],
         ]},

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-beam-mapper:
    <<: *ocs-base
    image: motor_test_image
    network_mode: "host"
    environment:
      LOGLEVEL: debug
    command:
      - "--instance-id=beammap-motors"


Agent API
---------

.. autoclass:: agents.appmotion_motor.appmotion_motors_agent.appMotionMotorsAgent
    :members:

Example Clients
---------------

Below is a script for a beam-mapper scan using the appmotion_motor_agent.::

    import numpy as np
    import time
    import os
    import sys

    # Importing OCS for motor control
    from ocs import matched_client
    import ocs

    # Make list of points to map
    def gen_points(Xstart,Xstop,Xstep,Ystart,Ystop,Ystep):

        if ( (Xstop-Xstart)%Xstep !=0 ) or ((Ystop-Ystart)%Ystep !=0):
            print('steplength is invalid')
            sys.exit("Error message...... program is aborting...")
        else:
            mappointX = abs(int((Xstop-Xstart)/Xstep))+1
            mappointY = abs(int((Ystop-Ystart)/Ystep))+1
            print('generate beammappoint %d x %d' %(mappointX, mappointY))
            mappoint = []
            xposition = Xstart
            for x in range(mappointX):
                yposition = Ystart
                for y in range(mappointY):
                    position = [xposition,yposition]
                    mappoint.append(position)
                    yposition += Ystep
                xposition +=Xstep

        return mappoint

    # Map points
    def scan_2d(mappoint,int_time,velocity):
        print('Initializing motors')
        motors = matched_client.MatchedClient('beammap-motors', args=[])
        motors.init_motors.start()
        motors.init_motors.wait()

        print(f'Setting velocity to {velocity} rev/s')
        motors.set_velocity.start(motor=3,velocity=velocity)
        motors.set_velocity.wait()

        print('Homing stages with limit switches')

        motors.home_with_limits.start(motor=3)
        motors.home_with_limits.wait()

        print(f'Taking data with integration time: {int_time} sec')

        time_dict = {}

        file_time = str(int(np.floor(time.time())))
        file_name = os.path.join('/home/gir/repos/ocs-site-configs/ucsd/k2so/gir/client_scripts/beam_maps/time_dicts',
                                    file_time+'_time_dict.txt')

        for point in mappoint:
            time_dict[str(point)] = []
            print(f'Moving stages to ({point[0]},{point[1]})')

            motors.acq.stop()
            motors.acq.wait()

            motors.run_positions.start(posData=point,posIsInches=True,motor=3)
            motors.run_positions.wait()

            status, msg, session = motors.is_moving.start(motor=3)
            status, msg, session = motors.is_moving.wait()
            move_status = session['messages'][1][1][1]

            motors.acq.start()

            time.sleep(1)

            while move_status:
                print('Motors are still moving. Sleeping 5 seconds.')
                time.sleep(5)

                motors.acq.stop()
                motors.acq.wait()

                status, msg, session = motors.is_moving.start(motor=3)
                status, msg, session = motors.is_moving.wait()
                move_status = session['messages'][1][1][1]

                motors.acq.start()


            motors.acq.stop()
            motors.acq.wait()

            status, msg, session = motors.get_encoder.start(motor=3)
            status, msg, session = motors.get_encoder.wait()

            ePositions = session['messages'][1][1][1]

            motors.acq.start()

            start_time = time.time()
            time_dict[str(point)].append(start_time)

            print(f'Taking data for {int_time} sec')
            time.sleep(int_time)

            stop_time = time.time()

            time_dict[str(point)].append(stop_time)

            with open(file_name, 'a') as fname:
                fname.write(f'start: {start_time}, stop : {stop_time}, ePositions: {ePositions}\n')

        time_dict_fp = os.path.join('/home/gir/repos/ocs-site-configs/ucsd/k2so/gir/client_scripts/beam_maps/time_dicts',
                                    file_time+'_time_dict.npy')
        print(f'Saving timestamps to {time_dict_fp}')
        np.save(time_dict_fp,time_dict)

        print('Done taking data. Moving stages back to home.')
        motors.run_positions.start(posData=(0.,0.),posIsInches=True,motor=3)
        motors.run_positions.wait()

        status, msg, session = motors.is_moving.start(motor=3)
        status, msg, session = motors.is_moving.wait()
        move_status = session['messages'][1][1][1]

        motors.acq.start()

        time.sleep(1)

        while move_status:
            print('Motors are still moving. Sleeping 5 seconds.')
            time.sleep(5)

            motors.acq.stop()
            motors.acq.wait()

            status, msg, session = motors.is_moving.start(motor=3)
            status, msg, session = motors.is_moving.wait()
            move_status = session['messages'][1][1][1]

            motors.acq.start()

        motors.acq.stop()
        motors.acq.wait()

        print('Closing motor connection')
        motors.close_connect.start(motor=3)
        motors.close_connect.wait()

        return time_dict_fp

Supporting APIs
---------------

.. autoclass:: agents.appmotion_motor.appmotion_motors_driver.Motor
    :members:

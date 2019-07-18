Creating New Agents
===================

In OCS, Agents are the software programs that contain the information you need
to do something useful. Agents can be used to communicate with hardware, or to
perform functions on preexisting data files. This guide will teach you how to
write a basic agent that can publish data to a feed.

Basics and Dependencies
-----------------------
An Agent is generally written as a Python class, and relies on modules
from OCS (including ``ocs_agent``, ``site_config``, ``client_t``, and
``ocs_twisted``). You must have OCS and all of its dependencies installed in
order to create and use an agent.

The OCS scripts ``ocs_agent``, ``site_config``, and ``client_t`` contain the
functionality required to register and run an agent using OCS and the crossbar
server. Functions from these scripts need to be called in order to

First Steps
-----------
The purpose of an Agent is to provide any functionality that you may need in
order to do something, so it is generally useful to create a Python class for
the Agent. Your class should contain functions for any use to which you might
want to put your Agent; as such, the agent class can be as simple or complex
as you need it to be.

The ``__init__`` function of the class should contain the ability for your
agent to register functions in OCS (this will be addressed in more detail in 
the Registration and Running section of this guide). This can be added by 
including an ``agent`` variable in the function, which we will establish later 
with an ``ocs_agent`` function. A simple initialization function is given by 
the ``ArduinoAgent`` class:

::

  def __init__(self, agent, port):
      self.active = True
      self.agent = agent
      self.log = agent.log
      self.lock = TimeoutLock()
      self.port = port
      self.take_data = False
      self.arduino = Arduino(port = self.port)

      self.initialized = False

      agg_params = {'frame_length':60}
      self.agent.register_feed('amplitudes', record=True, agg_params=agg_params,
       buffer_time=1)


The ``agent`` variable provides both the log and the data feed, which are
important for storing and logging data through OCS. The ``__init__`` function
also includes the ``ocs_twisted`` class ``TimeoutLock``, which will be used in
every function of your class (see the next paragraph for more on this). The
function additionally sets a dictionary of ``agg_params`` (aggregator
parameters), which are used to inform the aggregator of the length of the G3
frames in which the data will be stored. The final line of the ``__init__``
function registers the feed with the aggregator, and requires four inputs:
the type of data being taken (here called ``'amplitudes'``), the ``record``
condition set to ``True``, the parameter dictionary, and a buffer time, usually
set to 1.

In some Agents, it is convenient to create a separate class (or even an external
driver file) to write functions that the Agent class can call, but do not need
to be included in the OCS-connected Agent directly. In the case of the Arduino
agent, a separate Arduino class is written to make a serial connection to the
Arduino and read data. Other Agents may require more complex
helper classes and driver files (see ``LS240_Agent`` for an example).

Generally, a good first step in creating a function is to *lock* the function.
Locking checks that you are not running multiple functions simultaneously,
which helps to ensure that the Agent does not break if multiple functions are
mistakenly attempted at the same time. In order to lock the function, we use
the ``TimeoutLock`` class of ``ocs_twisted``. If a function cannot obtain the
lock, the script should ensure that it does not start. The rest of the function
should continue with this lock set. An example of the locking mechanism with an 
Arduino initialization function is written as follows:

::

        with self.acquire_timeout(timeout=0, job='init') as acquired:
                # Locking mechanism stops code from proceeding if no lock acquired
                if not acquired:
                        self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                        return False, "Could not acquire lock."
                # Run the function you want to run
                try:
                        self.arduino.read()
                except ValueError:
                        pass
                print("Arduino initialized")
        # This part is for the record and to allow future calls to proceed, so does not require the lock
        self.initialized = True
        return True, 'Arduino initialized.'


Registration and Running
------------------------
After writing the necessary functions in the Agent class, we need to activate
the Agent through OCS. While the form of this activation will change slightly
depending on the Agent's purpose, there are a few steps that are necessary to
get our Agent up and running: adding arguments with ``site_config``, parsing
arguments, initializing the Agent with ``ocs_agent``, and registering tasks and
processes.

OCS divides the functions that Agents can run into two categories:

- *Tasks* are functions that have a built-in end. An example of this type of
  function would be one that sets the power on a heater.
- *Processes* are functions that run continuously unless they are told to stop
  by the user, or perhaps another function. An example of this type of function
  is one that acquires data from a piece of hardware.

A simple example of this process can be found in the Arduino agent:

::

  if __name__ == '__main__':

    # Create an argument parser
    parser = site_config.add_arguments()

    # Tell OCS that the kind of arguments you're adding are for an agent
    pgroup = parser.add_argument_group('Agent Options')

    # Tell OCS to read the arguments
    args = parser.parse_args()

    # Process arguments, choosing the class that matches 'ArduinoAgent'
    site_config.reparse_args(args, 'ArduinoAgent')

    # Create a session and a runner which communicate over WAMP
    agent, runner = ocs_agent.init_site_agent(args)

    # Pass the new agent session to the agent class
    arduino_agent = ArduinoAgent(agent)

    # Register a task (name, agent_function)
    agent.register_task('init_arduino', arduino_agent.init_arduino)

    # Register a process (name, agent_start_function, agent_end_function)
    agent.register_process('acq', arduino_agent.start_acq, arduino_agent.stop_acq, startup=True)

    # Run the agent
    runner.run(agent, auto_reconnect=True)

If desired, ``pgroup`` may also have arguments (see ``LS240_agent`` for an
example).

Example Agent
-------------
For clarity and completeness, the entire Arduino Agent is included here as an 
example of a simple Agent.

::

        from ocs import ocs_agent, site_config, client_t
        import time
        import threading
        import serial
        from ocs.ocs_twisted import TimeoutLock
        from autobahn.wamp.exception import ApplicationError

        # Helper Arduino class to establish how to read from the Arduino
        class Arduino:
                def __init__(self, port='/dev/ttyACM0', baud=9600, timeout=0.1):
                        self.com = serial.Serial(port=port, baudrate=baud, timeout=timeout)

                def read(self):
                        try:
                                data = bytes.decode(self.com.readline()[:-2])
                                num_data = float(data.split(' ')[1])
                                return num_data
                        except Exception as e:
                                print(e)

         # Agent class with functions for initialization and acquiring data
         class ArduinoAgent:
                def __init__(self, agent, port='/dev/ttyACM0'):
                        self.active = True
                        self.agent = agent
                        self.log = agent.log
                        self.lock = TimeoutLock()
                        self.port = port
                        self.take_data = False
                        self.arduino = Arduino(port=self.port)

                        self.initialized = False

                        agg_params = {'frame_length':60}
                        self.agent.register_feed('amplitudes', record=True, agg_params=agg_params, buffer_time=1}

                def init_arduino(self):
                        if self.initialized:
                                return True, "Already initialized."

                        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
                                if not acquired:
                                        self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                                        return False, "Could not acquire lock."
                                try:
                                        self.arduino.read()
                                except ValueError:
                                        pass
                                print("ARduino initialized.")
                        self.initialized = True
                        return True, "Arduino initialized."

                def start_acq(self, session, params):
                        f_sample = params.get('sampling frequency', 2.5)
                        sleep_time = 1/f_sample - 0.1
                        if not self.initialized:
                                self.init_arduino()
                        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
                                if not acquired:
                                        self.log.warn("Could not start acq because {} is already running".format(self.lock.job))
                                        return False, "Could not acquire lock."
                                session.set_status('running')
                                self.take_data = True
                                while self.take_data:
                                        data = {'timestamp':time.time(), 'block_name':'amps','data':{}}
                                        data['data']['amplitude'] = self.arduino.read()
                                        time.sleep(sleep_time)
                                        self.agent.publish_to_feed('amplitudes',data)
                                self.agent.feeds['amplitudes'].flush_buffer()
                        return True, 'Acquisition exited cleanly.'

                def stop_acq(self, session, params=None):
                        if self.take_data:
                                self.take_data = False
                                return True, 'requested to stop taking data.'
                        else:
                                return False, 'acq is not currently running.'

        if __name__ == '__main__':
                parser = site_config.add_arguments()

                pgroup = parser.add_argument_group('Agent Options')

                args = parser.parse_args()

                site_config.reparse_args(args, 'ArduinoAgent')

                agent, runnr = ocs_agent.init_site_agent(args)

                arduino_agent = ArduinoAgent(agent)

                agent.register_task('init_arduino', arduino_agent.init_arduino)
                agent.register_process('acq', arduino_agent.start_acq, arduino_agent.stop_acq, startup=True)

                runner.run(agent, auto_reconnect=True)


Configuration
-------------
Because the agent program needs to be implemented in OCS, writing the agent
file is not sufficient for running it. Before you can run your agent, you
need to add an Agent instance to your ``default.yaml`` or ``your_institution.yaml``
file. To do this, change directories to ``ocs-site-configs/your_institution``.
Within this directory, you should find a yaml file to establish your OCS
agents. Within this file, you should find (or create) a dictionary of hosts.
As an example, we use the registry and aggregator agents, which are
necessary for taking any data with OCS, as well as the Arduino agent.

::

  hosts:

    grumpy: {

        'agent-instances': [
            # Core OCS Agents
            {'agent-class': 'RegistryAgent',
             'instance-id': 'registry',
             'arguments': []},
            {'agent-class': 'AggregatorAgent',
             'instance-id': 'aggregator',
             'arguments': [['--initial-state', 'record'],
                           ['--time-per-file', '3600'],
                           ['--data-dir', '/data/']]},

            # Arduino
            {'agent-class': 'ArduinoAgent',
             'instance-id': 'arduino',
             'arguments': []},
        ]
    }

When adding a new Agent, the ``'agent-class'`` entry should match the name of
your class in the Agent file. The ``'arguments'`` entry should match any
arguments that you added to ``pgroup`` at the end of your Agent file.

In this example, the ``'agent-instances'`` are found under a host called 
``grumpy``, which in this case is the name of the host computer. However, when 
writing an Agent that will be broadly useful, we may choose to Dockerize the 
Agent (and its dependencies). For more on this, see the Docker section of this 
documentation.


Docker
------
A Docker container creates a virtual environment in which you can package 
applications with their libraries and dependencies. OCS is sometimes installed 
in a Docker container (for ease of installation). For Agents that are not 
meant solely to be used with one lab computer, it can be useful to add them to a 
Docker container as well. This requires creating a ``Dockerfile`` for your Agent 
and adding the Agent capabilites to your OCS Docker container in a 
``docker-compose.yml`` file. Adding your Agent in the ``docker-compose.yml`` file 
will also allow you to view your data feed when you run the Agent.

To create a ``Dockerfile``, change directories to the directory containing your 
Agent file. Within this directory, create a file called ``Dockerfile``. The format 
of this file is as follows (using the Arduino as an example):

::

        # SOCS Arduino Agent
        # socs Agent container for interacting with an Arduino

        # Use socs base image
        FROM socs:latest

        # Set the working directory to registry directory
        WORKDIR /app/agents/arduino/

        # Copy this agent into the app/agents directory
        COPY . /app/agents/arduino/

        # Run registry on container startup
        ENTRYPOINT ["python3", "-u", "arduino_agent.py"]


In this case, the ``WORKDIR``, ``COPY``, and ``ENTRYPOINT`` arguments are all set 
specifically to the correct directories and files for the Arduino agent. You can 
additionally connect the container to a Crossbar (WAMP) server; see the Sisock 
documentation for more on this. 

To include your new Agent among the services provided in your OCS Docker 
container, navigate to the ``docker-compose.yml`` file in the same sub-directory 
as your ``default.yaml`` or ``your_institution.yaml`` file. Within 
``docker-compose.yml``, you should find (or create) a list of services that the 
docker container provides. You can add your new agent following the example format:

::

  services:
    arduino:
      image: grumpy.physics.yale.edu/sisock-data-feed-server:v0.2.12-1-g52852b4
      environment:
          TARGET: arduino
          NAME: 'arduino'
          DESCRIPTION: "arduino"
          FEED: "amplitudes"
      logging:
        options:
          max-size: "20m"
          max-file: "10"

The ``image`` line of this template corresponds to your computer's live feed
server, which should be the same for all of your agents. The ``image`` entry
contains entries that allow the live feed to subscribe to the data
you are reading (under ``environment``), as well as entries for keeping logs
of your agent's activity (under ``logging``). The ``environment`` entries are:

- ``TARGET``: the same as the ``instance-id`` that you added in the previous
file. This is used to identify the agent you wish to monitor.
- ``NAME``: the name that appears in a live feed field name.
- ``DESCRIPTION``: a short description of the feed you are subscribing to (can
be a word or a short sentence).
- ``FEED``: the type of data you are reading. This must match the data type
used in the ``self.agent.register_feed()`` entry in your agent class.

The ``logging`` options limit the maximum file size of the logs and
automatically rotates them. This should generally remain constant for all of
your agents.

Final Steps
-----------
After setting up the agent, you can run it from the command line with

::

        python3 agent_name.py --instance-id=arduino

Here ``--instance-id`` is the same as that given in your ocs-site-configs
``default.yaml`` file. The agent will then run until it is manually ended. Once
you have a successfully running Agent, then you can build a Docker image for
it.

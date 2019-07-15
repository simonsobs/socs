Creating New Agents
===================

In OCS, agents are the software programs that contain the information you need
to do something useful. Agents can be used to communicate with hardware, or to
perform functions on preexisting data files. This guide will teach you how to
write a basic agent that can publish data to a feed.

Basics and Dependencies
-----------------------
An agent is generally written as a Python class, and must call on other scripts
from OCS (including ``ocs_agent``, ``site_config``, ``client_t``, and
``ocs_twisted``). You must have OCS and all of its dependencies installed in
order to create and use an agent.

The OCS scripts ``ocs_agent``, ``site_config``, and ``client_t`` contain the
functionality required to register and run an agent using OCS and the crossbar
server. Functions from these scripts need to be called in order to

First Steps
-----------
The purpose of an agent is to provide any functionality that you may need in
order to do something, so it is generally useful to create a Python class for
the agent. Your class should contain functions for any use to which you might
want to put your agent; as such, the agent class can be as simple or complex
as you need it to be.

The ``__init__`` function of the class should contain the ability for your
agent to register functions in OCS (this will be addressed more detail in the
? section of this guide). This can be added by including an ``agent`` variable
in the function, which we will establish later with an ``ocs_agent`` function.
A simple initialization function is given by the ``ArduinoAgent`` class:

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
file in which the data will be stored. The final line of the ``__init__``
function registers the feed with the aggregator, and requires four inputs:
the type of data being taken (here called ``'amplitudes'``), the ``record``
condition set to ``True``, the parameter dictionary, and a buffer time, usually
set to 1.

In some agents, it is convenient to create a separate class (or even an external
driver file) to write functions that the Agent class can call, but do not need
to be included in the OCS-connected agent directly. In the case of the Arduino
agent, a separate Arduino class is written to make a serial connection to the
Arduino and read data in a useful way. Other agents may require more complex
helper classes and driver files (see ``LS240_Agent`` for an example).

Generally, a good first step in creating a function is to *lock* the function.
Locking ensures that you are not running multiple functions simultaneously,
which helps to ensure that the agent does not break if multiple functions are
mistakenly attempted at the same time. In order to lock the function, we can
use the ``TimeoutLock`` class of ``ocs_twisted``. If a function cannot lock,
the script should ensure that it does not start. The rest of the function should
continue with this lock set.

Registration and Running
------------------------
After writing the necessary functions in the agent class, we need to activate
the agent through OCS. While the form of this activation will change slightly
depending on the agent's purpose, there are a few steps that are necessary to
get our agent up and running: adding arguments with ``site_config``, parsing
arguments, initializing the agent with ``ocs_agent``, and registering tasks and
processes.

OCS divides the functions that agents can run into two categories:

- *Tasks* are functions that have a built-in end. An example of this type of
  function would be one that sets the power on a heater.
- *Processes* are functions that run continuously unless they are stopped by
  another function. An example of this type of function is one that acquires
  data from a hardware component.

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

Configuration
-------------
Because the agent program needs to be implemented in OCS, writing the agent
file is not sufficient for running it. Before you can run your agent, you
need to:

1. Add an agent instance to your ``default.yaml`` or ``your_institution.yaml``
file. To do this, change directories to ``ocs-site-configs/your_institution``.
Within this directory, you should find a yaml file to establish your OCS
agents, as well as a ``docker-compose.yml`` file. Within the ``default`` or
``your_institution`` file, you should find (or create) a dictionary of hosts.
As an example, we use the registry and aggregator agents, which are
necessary to taking any data with OCS, as well as the Arduino agent.

::

  hosts:

    ocs-docker: {

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

When adding a new agent, the ``'agent-class'`` entry should match the name of
your class in the agent file. The ``'arguments'`` entry should match any
arguments that you added to ``pgroup`` at the end of your agent file.

Once you have added your agent to the ``default.yaml`` or ``your_institution.yaml``
file, you should open ``docker-compose.yml``. This file adds agent capabilities
to your OCS docker container. Within ``docker-compose.yml``, you should find
(or create) a list of services that the docker container provides. You can add
your new agent following the example format:

::

  services:

    arduino:
      image: grumpy.physics.yale.edu/sisock-data-feed-server:v0.2.12-1-g52852b4
      environment:
          TARGET: arduino
          NAME: 'arduino'
          DESCRIPTION: "arduino"
          FEED: "amplitudes"
          CROSSBAR_HOST: 10.10.10.7
          CROSSBAR_TLS_PORT: 8080
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
- ``CROSSBAR_HOST``: the address of your crossbar server, which is the same
for all of your agents.
- ``CROSSBAR_TLS_PORT``: the port of your crossbar server, which is the same
for all of your agents.

The ``logging`` options should generally remain constant for all of your agents.

Final Steps
-----------
After setting up the agent, you can run it from the command line with

::

        python3 agent_name.py

The agent will run until it is manually ended.

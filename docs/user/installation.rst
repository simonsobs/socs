.. _installation:

Installation
============

To checkout SOCS, clone the repository and run `setup.py`::

  git clone https://github.com/simonsobs/socs.git
  cd socs/
  pip3 install -r requirements.txt .

.. note::
    If you are expecting to develop socs code you should consider using
    the `-e` flag.

.. note::
    If you would like to install for just the local user, throw the `--user`
    flag when running `setup.py`.

The Agent scripts live in the ``agents/`` sub-directory of the
repository.  Take note of the full path to the ``agents`` directory,
as you will need to add it to the OCS site configuration file.

In some systems it may be advantageous to copy the scripts to a stable
deployment location, outside the source tree
(e.g. ``/usr/local/lib/socs``).  Currently SOCS does not provide any
installation script to assist with this, but ``cp -r`` will work.

To make the Agent scripts usable within OCS, you must:

- Ensure that the base ``ocs`` package is installed on the local
  system.
- Ensure that any additional package dependencies for Agent scripts
  are satisfied.  Note that you only need to install the dependencies
  for the specific Agents that you intend to run on the local system.
- Edit the local system's site config file to include the full path to
  the SOCS agents directory (see ``Configuration``).


Site Config File
----------------

A configured OCS host will contain a ``site config`` file, which
describes how to connect to the crossbar server and (if HostMaster is
in use) describes what Agent instances will run on the system.

To tell OCS about the SOCS agents, update the ``agent-paths`` setting
in the host configuration block for your host.  The ``agent-paths``
setting is a list of paths on the local system, which should already
include the path to the base OCS installations agents.  With that path
included, you should then be able to add agent instance entries that
refer to Agent classes defined in SOCS.

In the example below, we assume that the local hostname is
``special-host-1``.  The path to ``/usr/shared/lib/socs/agents`` has
been added to the ``agent-paths`` variable, and a new Agent instance
for the Lakeshore372 has been added to ``agent-instances`` list.  Note
that ... is a place-holder for other configuration text.

.. code-block:: yaml

  hub:
    ...

  hosts:
    ...

    special-host-1: {
      ...

      # List of paths to Agent plugin modules.
      'agent-paths': [
	'/usr/shared/lib/ocs_agents',
	'/usr/shared/lib/socs/agents',
      ],

      ...
      'agent-instances': [
        ...
        {'agent-class': 'Lakeshore372Agent',
         'instance-id': 'thermo1',
         'arguments': [['--serial-number', 'LSA21YC'],
                       ['--ip-address', '10.10.10.2']]},
        ...
      ]
      ...
    }


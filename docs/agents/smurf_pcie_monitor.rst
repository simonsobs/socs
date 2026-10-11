.. highlight:: rst

.. _smurf_pcie_monitor:

=========================
SMuRF PCIe Monitor Agent
=========================

The SMuRF PCIe Monitor Agent monitors a configurable subset of PCIe card
registers via the rogue 6 ZMQ server running inside the ``smurf-pcie-docker``
container.

.. argparse::
    :filename: ../socs/agents/smurf_pcie_monitor/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the SMuRF PCIe Monitor Agent we need to add a
``SmurfPcieMonitorAgent`` entry to our site configuration file. Here is an
example configuration block using all of the available arguments::

    {'agent-class': 'SmurfPcieMonitorAgent',
     'instance-id': 'smurf-pcie-monitor',
     'arguments': [
       '--zmq-addr', 'localhost:9100',
       '--reg-config', '/config/pcie_regs.yaml',
       '--poll-interval', '30',
     ]},

The ``--zmq-addr`` argument should point to the ZMQ server address exposed by
the ``smurf-pcie-docker`` container. The ``--reg-config`` argument is the path
to a YAML file specifying which registers to monitor. The ``--poll-interval``
argument sets the time in seconds between register polling cycles (default 30).

Docker Compose
``````````````

The SMuRF PCIe Monitor Agent should be configured to run in a Docker container.
Because it needs to reach the ZMQ server inside the ``smurf-pcie-docker``
container, the simplest approach is to use ``network_mode: host``. An example
docker compose service configuration is shown here::

  ocs-smurf-pcie-monitor:
    image: simonsobs/socs:latest
    <<: *log-options
    network_mode: host
    hostname: ocs-docker
    container_name: ocs-smurf-pcie-monitor
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    environment:
      - INSTANCE_ID=smurf-pcie-monitor
      - LOGLEVEL=info

Ensure the ``smurf-pcie-docker`` container is running and its ZMQ server is
accessible at the address specified in the site config.

Register Config
---------------

The agent reads a YAML file that specifies which rogue register paths to
monitor. Each entry specifies a rogue tree ``path`` and a short
``field_name`` used as the key in the published data feed. An example
``pcie_regs.yaml``::

    registers:
      # FPGA identification and uptime
      - path: "pcie.Core.AxiPcieCore.AxiVersion.FpgaVersion"
        field_name: "fpga_version"
      - path: "pcie.Core.AxiPcieCore.AxiVersion.UpTimeCnt"
        field_name: "uptime_cnt"
      - path: "pcie.Core.AxiPcieCore.AxiVersion.BuildStamp"
        field_name: "build_stamp"

      # FPGA system monitor (temperatures and voltages)
      - path: "pcie.Core.SysMon.Temperature"
        field_name: "fpga_temp_degc"
      - path: "pcie.Core.SysMon.VccInt"
        field_name: "vccint_v"
      - path: "pcie.Core.SysMon.VccAux"
        field_name: "vccaux_v"
      - path: "pcie.Core.SysMon.VccBram"
        field_name: "vccbram_v"

      # RSSI link status (per-link)
      - path: "pcie.Core.UdpGrp.RssiClient[0].OpenConn"
        field_name: "rssi0_open"
      - path: "pcie.Core.UdpGrp.RssiClient[1].OpenConn"
        field_name: "rssi1_open"
      - path: "pcie.Core.UdpGrp.RssiClient[2].OpenConn"
        field_name: "rssi2_open"

Only registers listed in this file will be polled. Register paths must match
the rogue variable tree as served by the ``smurf-pcie-docker`` ZMQ server.
You can discover available paths by running the PCIe GUI
(``start_gui.sh``) or by dumping the state with ``PcieDumpState.py``.

Description
-----------

The SMuRF system uses a KCU1500 PCIe card to route data between the ATCA
carrier boards and the data acquisition server over 10 GbE links. The PCIe
card firmware exposes diagnostic registers through a rogue variable tree. The
``smurf-pcie-docker`` container starts a rogue 6 server that makes these
registers accessible over a ZMQ interface.

This agent connects to that ZMQ server as a rogue 6 ``VirtualClient`` and
periodically reads the subset of registers specified in the YAML configuration
file. The values are published to an OCS feed for storage and monitoring.

Useful registers to monitor include:

- **FPGA version and uptime** -- confirms firmware identity and tracks resets.
- **System monitor** -- FPGA die temperature and supply voltages
  (``VccInt``, ``VccAux``, ``VccBram``).
- **RSSI link status** -- valid frame counts and drop counts for each of the
  six 10 GbE links to the carrier boards.
- **DMA stream monitors** -- inbound and outbound AXI stream frame counters.

The agent follows the socs robustness guidelines for agent-device connections.
If the ZMQ connection is lost (e.g. the ``smurf-pcie-docker`` container
restarts), the agent will automatically attempt to reconnect on the next poll
cycle and resume monitoring without requiring a restart.

Agent API
---------

.. autoclass:: socs.agents.smurf_pcie_monitor.agent.SmurfPcieMonitorAgent
    :members:

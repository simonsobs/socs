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

This agent requires ``pyrogue`` (part of the SLAC rogue framework), which is not
available via pip. A Dockerfile is provided in the agent directory that builds
on the ``smurf-pcie`` image and installs socs::

  docker build -t ocs-smurf-pcie-monitor:latest \
    -f socs/agents/smurf_pcie_monitor/Dockerfile .

The agent connects to a rogue 6 ZMQ server running in a separate
``smurf-pcie-docker`` container. Both containers should use
``network_mode: host`` so they can communicate over ``localhost``.

An example docker compose service for the **rogue server** container::

  smurf-pcie-server:
    image: ghcr.io/slaclab/smurf-pcie:R3.3.3
    network_mode: host
    container_name: smurf-pcie-server
    restart: unless-stopped
    devices:
      - /dev/datadev_0
    volumes:
      - ./shared:/shared
    command: python3 /shared/start_server.py --port 9200

An example docker compose service for the **OCS agent** container::

  ocs-smurf-pcie-monitor:
    image: ocs-smurf-pcie-monitor:latest
    network_mode: host
    hostname: smurf-srv24-docker
    container_name: ocs-smurf-pcie-monitor
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    environment:
      - INSTANCE_ID=smurf-pcie-monitor
      - SITE_HUB=ws://${CB_HOST}:8001/ws
      - SITE_HTTP=http://${CB_HOST}:8001/call
      - OCS_CONFIG_DIR=/config/smurf-srv24
      - LOGLEVEL=info

Ensure the rogue server container is running before starting the OCS agent.

Register Config
---------------

The agent reads a YAML file that specifies which rogue register paths to
monitor. Each entry specifies a rogue tree ``path`` and a short
``field_name`` used as the key in the published data feed. An example
``pcie_regs.yaml``::

    registers:
      # FPGA identification and uptime
      - path: "Core.AxiPcieCore.AxiVersion.FpgaVersion"
        field_name: "fpga_version"
      - path: "Core.AxiPcieCore.AxiVersion.UpTimeCnt"
        field_name: "uptime_cnt"
      - path: "Core.AxiPcieCore.AxiVersion.BuildStamp"
        field_name: "build_stamp"

      # FPGA system monitor (temperatures and voltages)
      - path: "Core.SysMon.Temperature"
        field_name: "fpga_temp_degc"
      - path: "Core.SysMon.VccInt"
        field_name: "vccint_v"
      - path: "Core.SysMon.VccAux"
        field_name: "vccaux_v"
      - path: "Core.SysMon.VccBram"
        field_name: "vccbram_v"

      # RSSI link status (per-link)
      - path: "Core.UdpGrp.RssiClient[0].OpenConn"
        field_name: "rssi0_open"
      - path: "Core.UdpGrp.RssiClient[1].OpenConn"
        field_name: "rssi1_open"
      - path: "Core.UdpGrp.RssiClient[2].OpenConn"
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

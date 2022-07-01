from ocs.ocs_client import OCSClient


class MultiSlotController:
    """
    Simple client controller useful for managing all pysmurf-controller
    agents that exist on a network. This can dispatch operations and check
    operation status for any or all pysmurf-controllers on a network.

    Args
    -----
    client_args: list
        List of command line arguments to pass onto the OCSClient objects.

    Attributes
    ---------------
    smurfs : dict
        Dictionary containing OCSClient objects for each pysmurf-controller
        on the network. This assumes pysmurf controller agents have
        instance-id's of the form ``pysmurf-controller-<id>`` where id
        can be the uxm-id or something like ``crate1slot2``. The keys of this
        dict will be ``<id>``. This is populated from the registry agent on
        init or using the funciton ``get_active_smurfs``.

    Example
    ----------
    >>> msc = MultiSlotController()
    >>> print(msc.keys())
    dict_keys(['c1s2', 'c1s3', 'c1s4', 'c1s5', 'c1s6', 'c1s7'])
    >>> msc.start('uxm_setup')  # Run UXM Setup on all slots
    >>> # Waits for all slots to finish setup. You should monitor logs or check
    >>> # returned session-data to make sure this ran correctly
    >>> msc.wait('uxm_setup')
    >>> # Streams for 30 seconds on slots 2 and 3
    >>> msc.start('stream', ids=['c1s2', 'c1s3'], duration=30)
    >>> msc.wait('stream')  # Waits for controllers to finish streaming

    """

    def __init__(self, client_args=[]):
        self.client_args = client_args
        self.reg = OCSClient('registry', args=client_args)
        self.smurfs = {}
        self.get_active_smurfs()

    def get_active_smurfs(self):
        """
        Obtains a list of active pysmurf-controller agents on a network from
        the registry agent. Uses this to populate the ``smurfs`` dictionary,
        which contains an OCSClient object for each.
        """
        reg_agents = self.reg.main.status().session['data']
        self.smurfs = {}
        for k, v in reg_agents.items():
            if 'pysmurf-controller' not in k:
                continue
            if v['expired']:
                continue

            instance_id = k.split('.')[-1]
            smurf_key = instance_id.split('-')[-1]
            self.smurfs[smurf_key] = OCSClient(instance_id,
                                               args=self.client_args)

    def start(self, op_name, ids=None, **kwargs):
        """
        Starts an operation on any or all pysmurf controllers.

        Args
        ----
        op_name : str
            Name of the operation to start
        ids : list, optional
            List of pysmurf-controller id's. This defaults to running on all
            controllers.
        **kwargs
            Any additional keyword arguments are passed onto the start
            operation as params
        """
        if ids is None:
            ids = list(self.smurfs.keys())
        elif isinstance(ids, str):
            ids = [ids]
        rv = {}
        for smurf_id in ids:
            rv[smurf_id] = getattr(self.smurfs[smurf_id], op_name).start(**kwargs)
        return rv

    def stop(self, op_name, ids=None, **kwargs):
        """
        Stops an operation on any or all pysmurf controllers.

        Args
        ----
        op_name : str
            Name of the operation to stop
        ids : list, optional
            List of pysmurf-controller id's. This defaults to running on all
            controllers.
        **kwargs
            Any additional keyword arguments are passed onto the stop operation
            as params
        """
        if ids is None:
            ids = list(self.smurfs.keys())
        elif isinstance(ids, str):
            ids = [ids]
        rv = {}
        for smurf_id in ids:
            rv[smurf_id] = getattr(self.smurfs[smurf_id], op_name).stop(**kwargs)
        return rv

    def status(self, op_name, ids=None):
        """
        Checks the status of an operation on any or all pysmurf controllers

        Args
        ----
        op_name : str
            Name of the operation to stop
        ids : list, optional
            List of pysmurf-controller id's. This defaults to running on all
            controllers.
        """
        if ids is None:
            ids = list(self.smurfs.keys())
        elif isinstance(ids, str):
            ids = [ids]
        rv = {}
        for smurf_id in ids:
            rv[smurf_id] = getattr(self.smurfs[smurf_id], op_name).status()
        return rv

    def wait(self, op_name, ids=None):
        """
        Waits for an operation to finish on any or all pysmurf controllers.
        This will block until the operation sessions of all speicified ID's
        have been completed.

        Args
        ----
        op_name : str
            Name of the operation to stop
        ids : list, optional
            List of pysmurf-controller id's. This defaults to running on all
            controllers.
        """
        if ids is None:
            ids = list(self.smurfs.keys())
        elif isinstance(ids, str):
            ids = [ids]
        rv = {}
        for smurf_id in ids:
            rv[smurf_id] = getattr(self.smurfs[smurf_id], op_name).wait()
        return rv

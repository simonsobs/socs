"""Test for Cryomech cpa error handling.

IMPORTANT: The ocs site config file needs to have ['fake-errors', True]
passed as an argument to the compressor for this test to work.

This test passes a bad string instead of the real compressor data
to the agent 50% of the time. A sucessful test involves the agent
continuing to acquire data despite the bad string, and printing the
string ("FAKE ERROR") to the container logs. 

This test requires the ability to acquire data from a compressor.
The instance ID will need to be modified depending on your local setup.
"""

from ocs import matched_client

ptc1 = matched_client.MatchedClient('ptc1', args=[])

ptc1.init.start()
ptc1.init.wait()

status, msg, session = ptc1.acq.start()

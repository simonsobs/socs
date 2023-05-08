"""
Testing agent below
"""
# from ocs.ocs_client import OCSClient
# pol_grid = OCSClient('polarizing-grid', args=[])

# pol_grid.init_motor()
# pol_grid.close_connect()"



"""
Testing driver code below
"""
import pgrid_motor_driver as pgrid
pol_grid = pgrid("10.10.10.188", "4002", "pol_grid")
pol_grid.is_moving(self, verbose=True)

import os
from lndmanage import settings

settings.CACHING_RETENTION_MINUTES = 0

# constants for testing
SLEEP_SEC_AFTER_REBALANCING = 2

# testing base folder
test_dir = os.path.dirname(os.path.realpath(__file__))
bin_dir = os.path.join(test_dir, 'bin')
graph_definitions_dir = os.path.join(test_dir, 'graph_definitions')
test_data_dir = os.path.join(test_dir, 'test_data')

# set lndmanage_home path to be in the test_data folder and make sure the
# folder exists
lndmanage_home = os.path.join(test_data_dir, 'lndmanage')
try:
    os.mkdir(lndmanage_home)
except FileExistsError:
    pass

test_graphs_paths = {
    'small_star_ring': os.path.join(
    graph_definitions_dir, 'small_star_ring.py'),
}


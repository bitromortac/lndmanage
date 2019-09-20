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

test_graphs_paths = {
    'small_star_ring': os.path.join(
    graph_definitions_dir, 'small_star_ring.py'),
}


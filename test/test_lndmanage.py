"""
Integration tests for lndmanage.
"""
from test.testnetwork import TestNetwork
from test.testing_common import test_graphs_paths


class NewNode(TestNetwork):
    """
    NewNode tests behavior of lndmanage under a blank new node without any
    channels.
    """
    network_definition = test_graphs_paths['empty_graph']

    def graph_test(self):
        self.assertEqual(1, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(0, self.master_node_networkinfo['num_channels'])

    def test_empty(self):
        # LND interface of lndmanage is initialized in setUp method of super
        # class, so nothing is needed here.
        pass

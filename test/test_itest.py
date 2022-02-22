"""
Integration tests for lndmanage.
"""
from test.testing_common import test_graphs_paths, TestNetwork


class NewNode(TestNetwork):
    """
    NewNode tests behavior of lndmanage under a blank new node without any
    channels.
    """
    network_definition = test_graphs_paths['empty_graph']

    def graph_test(self):
        self.assertEqual(0, len(self.master_node_graph_view))

    def test_empty(self):
        # LND interface of lndmanage is initialized in setUp method of super
        # class, so nothing is needed here.
        pass

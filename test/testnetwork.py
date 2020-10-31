"""
Defines a general live test network class for integration testing.
"""
from unittest import TestCase

from lnregtest.lib.network import Network

from lndmanage.lib.node import LndNode

from test.testing_common import (
    bin_dir,
    test_data_dir,
)

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class TestNetwork(TestCase):
    """
    Class for spinning up simulated Lightning Networks to do integration
    testing.

    The implementation inheriting from this class needs to implement the
    graph_test method, which tests properties specific to the chosen test
    network graph. The attribute network_definition is a string that points
    to the file location of a network graph definition in terms of a dict.
    """
    network_definition = None

    def setUp(self):
        if self.network_definition is None:
            self.skipTest("This class doesn't represent a real test case.")
            raise NotImplementedError("A network definition path needs to be "
                                      "given.")

        self.testnet = Network(
            binary_folder=bin_dir,
            network_definition_location=self.network_definition,
            nodedata_folder=test_data_dir,
            node_limit='H',
            from_scratch=True
        )
        self.testnet.run_nocleanup()
        # to run the lightning network in the background and do some testing
        # here, run:
        # $ lnregtest --nodedata_folder /path/to/lndmanage/test/test_data/
        # self.testnet.run_from_background()

        # logger.info("Generated network information:")
        # logger.info(format_dict(self.testnet.node_mapping))
        # logger.info(format_dict(self.testnet.channel_mapping))
        # logger.info(format_dict(self.testnet.assemble_graph()))

        master_node_data_dir = self.testnet.master_node.data_dir
        master_node_port = self.testnet.master_node._grpc_port
        self.master_node_networkinfo = self.testnet.master_node.getnetworkinfo()

        self.lndnode = LndNode(
            lnd_home=master_node_data_dir,
            lnd_host='localhost:' + str(master_node_port),
            regtest=True
        )
        self.graph_test()

    def tearDown(self):
        self.testnet.cleanup()

    def graph_test(self):
        """
        graph_test should be implemented by each subclass test and check,
        whether the test graph has the correct shape.
        """
        raise NotImplementedError

import os, time
from unittest import TestCase

from lib.node import LndNode
from lib.listchannels import ListChannels
from lib.rebalance import Rebalancer
from lnregtest.lib.network import RegtestNetwork
from lnregtest.lib.utils import format_dict, dict_comparison

import _settings
import logging.config
logging.config.dictConfig(_settings.logger_config)
logger = logging.getLogger(__name__)

test_dir = os.path.dirname(os.path.realpath(__file__))
bin_dir = os.path.join(test_dir, 'bin')
graph_definitions = os.path.join(test_dir, 'graph_definitions')
small_star_ring_location = os.path.join(graph_definitions, 'small_star_ring.py')
test_data_dir = os.path.join(test_dir, 'test_data')

# important to set the cache time to zero, otherwise one will
# have unexpected behavior of the tests
_settings.CACHING_RETENTION_MINUTES = 0


class TestRebalance(TestCase):
    def setUp(self):
        self.testnet = RegtestNetwork(
            binary_folder=bin_dir,
            network_definition_location=small_star_ring_location,
            nodedata_folder=test_data_dir,
            node_limit='H',
            from_scratch=True
        )
        # run network and print information
        self.testnet.run_nocleanup()
        # to run the lightning network in the background and do some testing
        # here, run:
        # $ lnregtest --nodedata_folder /path/to/lndmanage/test/test_data/
        # self.testnet.run_from_background()

        logger.info("Generated network information:")
        logger.info(format_dict(self.testnet.node_mapping))
        logger.info(format_dict(self.testnet.channel_mapping))
        logger.info(format_dict(self.testnet.assemble_graph()))

        master_node_data_dir = self.testnet.master_node.lnd_data_dir
        master_node_port = self.testnet.master_node.grpc_port

        # initialize lndnode
        self.lndnode = LndNode(
            lnd_home=master_node_data_dir,
            lnd_host='localhost:' + str(master_node_port),
            regtest=True
        )
        self.lndnode.print_status()
        logger.info('Initializing done.')

    def test_rebalance_channel_6(self):
        listchannels = ListChannels(self.lndnode)
        listchannels.print_all_channels('rev_alias')

        rebalancer = Rebalancer(
            self.lndnode,
            max_effective_fee_rate=50,
            budget_sat=20
        )
        # graph state before
        graph_should = self.testnet.assemble_graph()

        # channel A-B, defined as channel 1
        # channel A-C, defined as channel 2
        # channel A-D, defined as channel 6
        # TODO: test channel 1 and 2, which are currently failing to rebalance
        test_channel_number = 6
        channel_id = self.testnet.channel_mapping[
            test_channel_number]['channel_id']
        logger.info('Testing rebalancing of channel: {}'.format(channel_id))

        # rebalance channel
        rebalancer.rebalance(
            channel_id,
            dry=False,
            chunksize=1.0,
            target=0.0,
            allow_unbalancing=False
        )
        graph_is = self.testnet.assemble_graph()

        dict_comparison(graph_should, graph_is, show_diff=True)

        listchannels = ListChannels(self.lndnode)
        listchannels.print_all_channels('rev_alias')

    def tearDown(self):
        self.testnet.cleanup()

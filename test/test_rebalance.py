"""
Integration tests for rebalancing of channels.
"""
import time

from lndmanage import settings
from lndmanage.lib.listchannels import ListChannels
from lndmanage.lib.rebalance import Rebalancer
from lndmanage.lib.ln_utilities import channel_unbalancedness_and_commit_fee
from lndmanage.lib.exceptions import RebalanceCandidatesExhausted
from test.testnetwork import TestNetwork

from test.testing_common import (
    lndmanage_home,
    test_graphs_paths,
    SLEEP_SEC_AFTER_REBALANCING)

import logging.config
settings.set_lndmanage_home_dir(lndmanage_home)
logging.config.dictConfig(settings.logger_config)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.handlers[0].setLevel(logging.DEBUG)


class RebalanceTest(TestNetwork):
    """
    Implements an abstract testing class for channel rebalancing.
    """
    def rebalance_and_check(self, test_channel_number, target,
                            allow_unbalancing, places=5):
        """
        Test function for rebalancing to a specific target unbalancedness and
        asserts afterwards that the target was reached.

        :param test_channel_number: channel id
        :type test_channel_number: int
        :param target: unbalancedness target
        :type target: float
        :param allow_unbalancing: if unbalancing should be allowed
        :type allow_unbalancing: bool
        :param places: accuracy of the comparison between expected and tested
            values
        :type places: int
        """
        rebalancer = Rebalancer(
            self.lndnode,
            max_effective_fee_rate=50,
            budget_sat=20
        )

        channel_id = self.testnet.channel_mapping[
            test_channel_number]['channel_id']

        try:
            fees_msat = rebalancer.rebalance(
                channel_id,
                dry=False,
                chunksize=1.0,
                target=target,
                allow_unbalancing=allow_unbalancing
            )
        except Exception as e:
            raise e

        # sleep a bit to let LNDs update their balances
        time.sleep(SLEEP_SEC_AFTER_REBALANCING)

        # check if graph has the desired channel balances
        graph = self.testnet.assemble_graph()
        channel_data = graph['A'][test_channel_number]
        listchannels = ListChannels(self.lndnode)
        listchannels.print_all_channels('rev_alias')

        channel_unbalancedness, _ = channel_unbalancedness_and_commit_fee(
            channel_data['local_balance'],
            channel_data['capacity'],
            channel_data['commit_fee'],
            channel_data['initiator']
        )

        self.assertAlmostEqual(
            target, channel_unbalancedness, places=places)

        return fees_msat

    def graph_test(self):
        """
        graph_test should be implemented by each subclass test and check,
        whether the test graph has the correct shape.
        """
        raise NotImplementedError


class TestLiquidRebalance(RebalanceTest):
    network_definition = test_graphs_paths['star_ring_3_liquid']

    # channels:
    # A -> B (channel #1)
    # A -> C (channel #2)
    # A -> D (channel #6)
    # B -> C (channel #3)
    # B -> D (channel #4)
    # C -> D (channel #5)

    def graph_test(self):
        self.assertEqual(4, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(6, self.master_node_networkinfo['num_channels'])

    def test_rebalance_channel_6(self):
        test_channel_number = 6
        self.rebalance_and_check(test_channel_number, 0.0, False)

    def test_small_positive_target_channel_6(self):
        test_channel_number = 6
        self.rebalance_and_check(test_channel_number, 0.2, False)

    def test_large_positive_channel_6(self):
        test_channel_number = 6
        self.rebalance_and_check(test_channel_number, 0.8, False)

    def test_small_negative_target_channel_6_fail(self):
        # this test should fail when unbalancing is not allowed, as it would
        # unbalance another channel if the full target would be accounted for
        test_channel_number = 6
        self.assertRaises(
            RebalanceCandidatesExhausted,
            self.rebalance_and_check, test_channel_number, -0.2, False)

    def test_small_negative_target_channel_6_succeed(self):
        # this test should fail when unbalancing is not allowed, as it would
        # unbalance another channel if the full target would be accounted for
        test_channel_number = 6
        self.rebalance_and_check(test_channel_number, -0.2, True)

    def test_rebalance_channel_1(self):
        test_channel_number = 1
        self.rebalance_and_check(test_channel_number, 0.0, False)

    def test_rebalance_channel_2(self):
        test_channel_number = 2
        self.rebalance_and_check(test_channel_number, 0.0, False, places=1)

    def test_shuffle_arround(self):
        """
        Shuffles sat around in channel 6.
        """
        first_target_amount = -0.1
        second_target_amount = 0.1
        test_channel_number = 6

        self.rebalance_and_check(
            test_channel_number, first_target_amount, True)
        self.rebalance_and_check(
            test_channel_number, second_target_amount, True)


class TestUnbalancedRebalance(RebalanceTest):
    network_definition = test_graphs_paths['star_ring_4_unbalanced']

    # channels:
    # A -> B (channel #1)
    # A -> C (channel #2)
    # A -> D (channel #3)
    # A -> E (channel #4)

    def graph_test(self):
        self.assertEqual(5, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(10, self.master_node_networkinfo['num_channels'])

    def test_rebalance_channel_1(self):
        """tests multiple rebalance of one channel"""
        test_channel_number = 1
        # TODO: find out why not exact rebalancing target is reached
        print(self.rebalance_and_check(
            test_channel_number, -0.05, False, places=1))


class TestIlliquidRebalance(RebalanceTest):
    network_definition = test_graphs_paths['star_ring_4_illiquid']

    # channels:
    # A -> B (channel #1)
    # A -> C (channel #2)
    # A -> D (channel #3)
    # A -> E (channel #4)

    def graph_test(self):
        self.assertEqual(5, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(10, self.master_node_networkinfo['num_channels'])

    def test_rebalance_channel_1(self):
        """
        Tests multiple payment attempt rebalancing.
        """
        test_channel_number = 1
        # TODO: find out why not exact rebalancing target is reached
        fees_msat = self.rebalance_and_check(
            test_channel_number, -0.05, False, places=1)
        self.assertEqual(2575, fees_msat)

    def test_rebalance_channel_1_fail(self):
        """
        Tests if there are no rebalance candidates, because the target
        requested doesn't match with the other channels.
        """
        test_channel_number = 1
        self.assertRaises(
            RebalanceCandidatesExhausted, self.rebalance_and_check,
            test_channel_number, 0.3, False, places=1
        )

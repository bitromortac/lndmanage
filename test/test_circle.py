"""
Tests for circular self-payments.
"""
import time
from unittest import TestCase

from lnregtest.lib.network import RegtestNetwork

from lndmanage.lib.node import LndNode
from lndmanage.lib.listchannels import ListChannels
from lndmanage.lib.rebalance import Rebalancer
from lndmanage.lib.exceptions import RebalanceFailure, TooExpensive
from lndmanage import settings

from test.testing_common import (
    bin_dir,
    test_data_dir,
    test_graphs_paths,
    lndmanage_home,
    SLEEP_SEC_AFTER_REBALANCING
)

import logging.config
settings.set_lndmanage_home_dir(lndmanage_home)
logging.config.dictConfig(settings.logger_config)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers[0].setLevel(logging.DEBUG)


class TestCircle(TestCase):
    def setUp(self):
        self.testnet = RegtestNetwork(
            binary_folder=bin_dir,
            network_definition_location=test_graphs_paths['star_ring_3_liquid'],
            nodedata_folder=test_data_dir,
            node_limit='H',
            from_scratch=True
        )
        self.testnet.run_nocleanup()

        master_node_data_dir = self.testnet.master_node.lnd_data_dir
        master_node_port = self.testnet.master_node.grpc_port
        master_node_networkinfo = self.testnet.master_node.getnetworkinfo()

        # assert some basic properties of the graph
        self.assertEqual(4, master_node_networkinfo['num_nodes'])
        self.assertEqual(6, master_node_networkinfo['num_channels'])

        self.lndnode = LndNode(
            lnd_home=master_node_data_dir,
            lnd_host='localhost:' + str(master_node_port),
            regtest=True
        )

        self.rebalancer = Rebalancer(
            self.lndnode,
            max_effective_fee_rate=50,
            budget_sat=20
        )

    def tearDown(self):
        self.testnet.cleanup()

    def circle_and_check(self, rebalancer, channel_number_send,
                         channel_number_receive, amount_sat,
                         expected_fees_msat):
        """
        Helper function for testing a circular payment.

        :param rebalancer:
        :type rebalancer: lndmanage.lib.rebalance.Rebalancer

        :param channel_number_send: channel whose local balance is decreased
        :type channel_number_send: int

        :param channel_number_receive: channel whose local balance is increased
        :type channel_number_receive: int

        :param amount_sat: amount in satoshi to rebalance
        :type amount_sat: int

        :param expected_fees_msat: expected fees in millisatoshi for
            the rebalance
        :type expected_fees_msat: int
        """
        # setup
        graph_before = self.testnet.assemble_graph()
        channel_id_send = self.testnet.channel_mapping[
            channel_number_send]['channel_id']
        channel_id_receive = self.testnet.channel_mapping[
            channel_number_receive]['channel_id']
        invoice_r_hash = self.lndnode.get_invoice(amount_sat, '')

        # exercise
        try:
            fees_msat = rebalancer.rebalance_two_channels(
                channel_id_send,
                channel_id_receive,
                amount_sat,
                invoice_r_hash,
                rebalancer.budget_sat
            )
            time.sleep(SLEEP_SEC_AFTER_REBALANCING)
        except Exception as e:
            raise e

        # check
        graph_after = self.testnet.assemble_graph()
        channel_data_send_before = graph_before['A'][channel_number_send]
        channel_data_receive_before = graph_before['A'][channel_number_receive]
        channel_data_send_after = graph_after['A'][channel_number_send]
        channel_data_receive_after = graph_after['A'][channel_number_receive]
        listchannels = ListChannels(self.lndnode)
        listchannels.print_all_channels('rev_alias')

        # test that the fees are correct
        self.assertEqual(fees_msat, expected_fees_msat)
        # test if sending channel's remote balance has increased correctly
        self.assertEqual(
            amount_sat,
            channel_data_send_after['remote_balance'] -
            channel_data_send_before['remote_balance'] -
            int(expected_fees_msat // 1000),
            "Sending local balance is wrong"
        )
        # test if receiving channel's local balance has increased correctly
        self.assertEqual(
            amount_sat,
            channel_data_receive_after['local_balance'] -
            channel_data_receive_before['local_balance'],
            "Receiving local balance is wrong"
        )

    def test_circle_1_2(self):
        """
        Test successful rebalance from channel 1 to channel 2.
        """
        channel_number_from = 1
        channel_number_to = 2
        amount_sat = 10000
        expected_fees_msat = 43

        self.circle_and_check(
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

    def test_circle_1_6(self):
        """
        Test successful rebalance from channel 1 to channel 6.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33

        self.circle_and_check(
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

    def test_circle_6_1_rebalance_failure_no_funds(self):
        """
        Test expected failure for channel 6 to channel 1, where channel 6
        doesn't have funds.
        """
        channel_number_from = 6
        channel_number_to = 1
        amount_sat = 10000
        expected_fees_msat = 33

        self.assertRaises(
            RebalanceFailure,
            self.circle_and_check,
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

    def test_circle_1_6_budget_too_expensive(self):
        """
        Test expected failure where rebalance uses more than the fee budget.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33
        self.rebalancer.budget_sat = 0

        self.assertRaises(
            TooExpensive,
            self.circle_and_check,
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

    def test_circle_1_6_max_fee_rate_too_expensive(self):
        """
        Test expected failure where rebalance is more expensive than
        the desired maximal fee rate.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33
        self.rebalancer.max_effective_fee_rate = 0

        self.assertRaises(
            TooExpensive,
            self.circle_and_check,
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

    def test_circle_1_6_fail_first_hop_insufficient_funds(self):
        """
        Tests failure when our channel fails because we didn't take into
        account channel reserve. (Failing channel 1: 117:1:0)
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 1000000
        expected_fees_msat = 33

        self.assertRaises(
            RebalanceFailure,
            self.circle_and_check,
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

    def test_circle_1_6_channel_reserve(self):
        """
        Test for a maximal amount circular payment.
        """
        channel_number_from = 1
        channel_number_to = 6
        local_balance = 1000000
        # take into account 1% channel reserve
        amount_sat = int(local_balance - 0.01 * local_balance)
        # need to also subtract commitment fees
        amount_sat -= 9050
        # need to also subtract fees, then error message changes
        amount_sat -= 3
        # extra to make it succeed
        amount_sat -= 2150

        expected_fees_msat = 2938

        self.circle_and_check(
            self.rebalancer,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

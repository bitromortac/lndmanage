"""
Tests for circular self-payments.
"""
import time

from lndmanage.lib.listchannels import ListChannels
from lndmanage.lib.rebalance import Rebalancer
from lndmanage.lib.exceptions import (
    RebalanceFailure,
    TooExpensive,
    DryRun,
    RebalancingTrialsExhausted,
    NoRoute,
    PolicyError,
    OurNodeFailure,
)
from lndmanage import settings
from test.testnetwork import TestNetwork

from test.testing_common import (
    test_graphs_paths,
    lndmanage_home,
    SLEEP_SEC_AFTER_REBALANCING
)

import logging.config
settings.set_lndmanage_home_dir(lndmanage_home)
logging.config.dictConfig(settings.logger_config)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.handlers[0].setLevel(logging.DEBUG)


class CircleTest(TestNetwork):
    """
    Implements testing of circular self-payments.
    """
    network_definition = None

    def circle_and_check(self, channel_number_send: int,
                         channel_number_receive: int, amount_sat: int,
                         expected_fees_msat: int, budget_sat=20,
                         max_effective_fee_rate=50, dry=False):
        """
        Helper function for testing a circular payment.

        :param channel_number_send: channel whose local balance is decreased
        :param channel_number_receive: channel whose local balance is increased
        :param amount_sat: amount in satoshi to rebalance
        :param expected_fees_msat: expected fees in millisatoshi for
            the rebalance
        :param budget_sat: budget for rebalancing
        :param max_effective_fee_rate: the maximal effective fee rate accepted
        :param dry: if it should be a dry run
        """

        self.rebalancer = Rebalancer(
            self.lndnode,
            max_effective_fee_rate=max_effective_fee_rate,
            budget_sat=budget_sat,
        )

        graph_before = self.testnet.assemble_graph()
        channel_id_send = self.testnet.channel_mapping[
            channel_number_send]['channel_id']
        channel_id_receive = self.testnet.channel_mapping[
            channel_number_receive]['channel_id']
        invoice = self.lndnode.get_invoice(amount_sat, '')
        payment_hash, payment_address = invoice.r_hash, invoice.payment_addr

        try:
            fees_msat = self.rebalancer.rebalance_two_channels(
                channel_id_send,
                channel_id_receive,
                amount_sat,
                payment_hash,
                payment_address,
                budget_sat,
                dry=dry
            )
            time.sleep(SLEEP_SEC_AFTER_REBALANCING)
        except Exception as e:
            raise e

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

    def graph_test(self):
        """
        graph_test should be implemented by each subclass test and check,
        wheteher the test graph has the correct shape.
        """
        raise NotImplementedError


class TestCircleLiquid(CircleTest):
    network_definition = test_graphs_paths['star_ring_3_liquid']

    def graph_test(self):
        # assert some basic properties of the graph
        self.assertEqual(4, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(6, self.master_node_networkinfo['num_channels'])

    def test_circle_success_1_2(self):
        """
        Test successful rebalance from channel 1 to channel 2.
        """
        channel_number_from = 1
        channel_number_to = 2
        amount_sat = 10000
        expected_fees_msat = 43

        self.circle_and_check(
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

    def test_circle_success_1_6(self):
        """
        Test successful rebalance from channel 1 to channel 6.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33

        self.circle_and_check(
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

    def test_circle_6_1_fail_rebalance_failure_no_funds(self):
        """
        Test expected failure for channel 6 to channel 1, where channel 6
        doesn't have funds.
        """
        channel_number_from = 6
        channel_number_to = 1
        amount_sat = 10000
        expected_fees_msat = 33

        self.assertRaises(
            OurNodeFailure,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

    def test_circle_1_6_fail_budget_too_expensive(self):
        """
        Test expected failure where rebalance uses more than the fee budget.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33
        budget_sat = 0

        self.assertRaises(
            TooExpensive,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
            budget_sat,
        )

    def test_circle_1_6_fail_max_fee_rate_too_expensive(self):
        """
        Test expected failure where rebalance is more expensive than
        the desired maximal fee rate.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33
        budget = 20
        max_effective_fee_rate = 0

        self.assertRaises(
            TooExpensive,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
            budget,
            max_effective_fee_rate,

        )

    def test_circle_1_6_success_channel_reserve(self):
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
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
        )

    def test_circle_1_6_fail_rebalance_dry(self):
        """
        Test if dry run exception is raised.
        """
        channel_number_from = 1
        channel_number_to = 6
        amount_sat = 10000
        expected_fees_msat = 33

        self.assertRaises(
            DryRun,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat,
            dry=True
        )


class TestCircleIlliquid(CircleTest):

    network_definition = test_graphs_paths['star_ring_4_illiquid']

    def graph_test(self):
        self.assertEqual(5, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(10, self.master_node_networkinfo['num_channels'])

    def test_circle_fail_2_3_no_route(self):
        """
        Test if NoRoute is raised.
        """
        channel_number_from = 2
        channel_number_to = 3
        amount_sat = 500000
        expected_fees_msat = None

        self.assertRaises(
            NoRoute,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

    def test_circle_1_2_fail_max_trials_exhausted(self):
        """
        Test if RebalancingTrialsExhausted is raised.
        """
        channel_number_from = 1
        channel_number_to = 2
        amount_sat = 190950
        expected_fees_msat = None
        settings.REBALANCING_TRIALS = 1

        self.assertRaises(
            RebalancingTrialsExhausted,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

    def test_circle_1_2_fail_no_route_multi_trials(self):
        """
        Test if RebalancingTrialsExhausted is raised.
        """
        channel_number_from = 1
        channel_number_to = 2
        amount_sat = 450000
        expected_fees_msat = None

        self.assertRaises(
            RebalancingTrialsExhausted,
            self.circle_and_check,
            channel_number_from,
            channel_number_to,
            amount_sat,
            expected_fees_msat
        )

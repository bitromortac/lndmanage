"""Tests for circular self-payments."""
import asyncio
import math
from decimal import Decimal
import time
from typing import List
import unittest

from test.testing_common import (
    test_graphs_paths,
    SLEEP_SEC_AFTER_REBALANCING,
    TestNetwork,
)

from lndmanage.lib.listings import ListChannels
from lndmanage.lib.rebalance import Rebalancer
from lndmanage.lib.exceptions import (
    TooExpensive,
    DryRun,
    RebalancingTrialsExhausted,
    NoRoute,
    OurNodeFailure,
)

from lndmanage import settings  # needed for side effect configuration


class CircleTest(TestNetwork):
    """Implements testing of circular self-payments.
    """
    network_definition = None

    async def circular_rebalance_and_check(
            self,
            channel_numbers_send: List[int],
            channel_numbers_receive: List[int],
            amount_sat: int,
            expected_fees_msat: int,
            budget_sat=20,
            max_effective_fee_rate=Decimal(50),
            dry=False
    ):
        """Helper function for testing a circular payment.

        :param channel_numbers_send: channels whose local balance is decreased
        :param channel_numbers_receive: channels whose local balance is increased
        :param amount_sat: amount in satoshi to rebalance
        :param expected_fees_msat: expected fees in millisatoshi for the rebalance
        :param budget_sat: budget for rebalancing
        :param max_effective_fee_rate: the maximal effective fee rate accepted
        :param dry: if it should be a dry run
        """

        async with self.lndnode:
            self.rebalancer = Rebalancer(
                self.lndnode
            )

            graph_before = self.testnet.assemble_graph()
            send_channels = {}
            self.rebalancer.channels = self.lndnode.get_unbalanced_channels()

            for c in channel_numbers_send:
                channel_id = self.testnet.channel_mapping[c]['channel_id']
                send_channels[channel_id] = self.rebalancer.channels[channel_id]
            receive_channels = {}
            for c in channel_numbers_receive:
                channel_id = self.testnet.channel_mapping[c]['channel_id']
                receive_channels[channel_id] = self.rebalancer.channels[channel_id]

            invoice = self.lndnode.get_invoice(amount_sat, '')
            payment_hash, payment_address = invoice.r_hash, invoice.payment_addr

            max_effective_fee_rate = min(
                max_effective_fee_rate if max_effective_fee_rate is not None else Decimal(1),
                budget_sat / amount_sat if budget_sat is not None else Decimal(1)
            )
            budget_sat = int(max_effective_fee_rate * abs(amount_sat))
            fees_msat = self.rebalancer._rebalance(
                send_channels=send_channels,
                receive_channels=receive_channels,
                amt_sat=amount_sat,
                payment_hash=payment_hash,
                payment_address=payment_address,
                budget_sat=budget_sat,
                force=True,
                dry=dry
            )

            time.sleep(SLEEP_SEC_AFTER_REBALANCING)  # needed to let lnd update the balances

            graph_after = self.testnet.assemble_graph()

            self.assertEqual(expected_fees_msat, fees_msat)

            # check that we send the amount we wanted and that it's conserved
            # TODO: this depends on channel reserves, we assume we opened the channels
            sent = 0
            received = 0
            for c in channel_numbers_send:
                sent += (graph_before['A'][c]['local_balance'] - graph_after['A'][c]['local_balance'])
            for c in channel_numbers_receive:
                received += (graph_before['A'][c]['remote_balance'] - graph_after['A'][c]['remote_balance'])
            assert sent - math.ceil(expected_fees_msat / 1000) == received

            listchannels = ListChannels(self.lndnode)
            listchannels.print_all_channels('rev_alias')

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
        self.assertEqual(6, len(self.master_node_graph_view))

    def test_circle_success_1_2(self):
        """
        Test successful rebalance from channel 1 to channel 2.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 10000
        expected_fees_msat = 43

        asyncio.run(self.circular_rebalance_and_check(
            channel_numbers_from,
            channel_numbers_to,
            amount_sat,
            expected_fees_msat
        ))

    def test_circle_success_1_6(self):
        """
        Test successful rebalance from channel 1 to channel 6.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        amount_sat = 10000
        expected_fees_msat = 33

        asyncio.run(self.circular_rebalance_and_check(
            channel_numbers_from,
            channel_numbers_to,
            amount_sat,
            expected_fees_msat
        ))

    def test_circle_6_1_fail_rebalance_failure_no_funds(self):
        """
        Test expected failure for channel 6 to channel 1, where channel 6
        doesn't have funds.
        """
        channel_numbers_from = [6]
        channel_numbers_to = [1]
        amount_sat = 10000
        expected_fees_msat = 33

        self.assertRaises(
            OurNodeFailure,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat
            )
        )

    def test_circle_1_6_fail_budget_too_expensive(self):
        """
        Test expected failure where rebalance uses more than the fee budget.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        amount_sat = 10000
        expected_fees_msat = 33
        budget_sat = 0

        self.assertRaises(
            TooExpensive,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
                budget_sat
            )
        )

    def test_circle_1_6_fail_max_fee_rate_too_expensive(self):
        """
        Test expected failure where rebalance is more expensive than
        the desired maximal fee rate.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        amount_sat = 10000
        expected_fees_msat = 33
        budget = 20
        max_effective_fee_rate = Decimal(0)

        self.assertRaises(
            TooExpensive,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
                budget,
                max_effective_fee_rate,
            )
        )

    def test_circle_1_6_success_channel_reserve(self):
        """
        Test for a maximal amount circular payment.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        local_balance = 1000000
        # take into account 1% channel reserve
        amount_sat = int(local_balance - 0.01 * local_balance)
        # need to subtract commitment fee (local + anchor output)
        amount_sat -= 3140
        # need to subtract anchor values
        amount_sat -= 330 * 2
        # need to also subtract fees, then error message changes
        amount_sat -= 3
        # extra to make it work for in-between nodes
        amount_sat -= 200
        # TODO: figure out exactly the localbalance - fees for initiator

        expected_fees_msat = 2_959

        asyncio.run(
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
            )
        )

    def test_circle_1_6_fail_rebalance_dry(self):
        """
        Test if dry run exception is raised.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        amount_sat = 10000
        expected_fees_msat = 33

        self.assertRaises(
            DryRun,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
                dry=True
            )
        )

    @unittest.skip
    def test_multi_send(self):
        pass

    @unittest.skip
    def test_multi_receive(self):
        pass


class TestCircleIlliquid(CircleTest):

    network_definition = test_graphs_paths['star_ring_4_illiquid']

    def graph_test(self):
        self.assertEqual(10, len(self.master_node_graph_view))

    def test_circle_fail_2_3_no_route(self):
        """Test if NoRoute is raised. We can't go beyond C."""
        channel_numbers_from = [2]  # A -> C
        channel_numbers_to = [3]  # D -> A
        amount_sat = 500_000
        expected_fees_msat = None

        self.assertRaises(
            NoRoute,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
            )
        )

    def test_circle_1_2_fail_max_trials_exhausted(self):
        """Test if RebalancingTrialsExhausted is raised.

        There will be a single rebalancing attempt, which fails, after which we don't retry.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 190950
        expected_fees_msat = None
        settings.REBALANCING_TRIALS = 1

        self.assertRaises(
            RebalancingTrialsExhausted,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
            )
        )

    def test_circle_1_2_fail_no_route_multi_trials(self):
        """Test if NoRoute is raised."""
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 450000
        expected_fees_msat = None

        self.assertRaises(
            RebalancingTrialsExhausted,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
            )
        )

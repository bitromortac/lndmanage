"""Tests for circular self-payments."""
import asyncio
import math
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
            max_effective_fee_rate=50,
            dry=False
    ):
        """Helper function to test a circular payment.

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
                self.lndnode,
                max_effective_fee_rate=max_effective_fee_rate,
                budget_sat=budget_sat,
                force=True,
            )

            graph_before = self.testnet.assemble_graph()

            self.rebalancer.channels = self.lndnode.get_unbalanced_channels()

            send_channels = {}
            for c in channel_numbers_send:
                channel_id = self.testnet.channel_mapping[c]['channel_id']
                send_channels[channel_id] = self.rebalancer.channels[channel_id]

            receive_channels = {}
            for c in channel_numbers_receive:
                channel_id = self.testnet.channel_mapping[c]['channel_id']
                receive_channels[channel_id] = self.rebalancer.channels[channel_id]

            fees_msat = self.rebalancer._rebalance(
                send_channels=send_channels,
                receive_channels=receive_channels,
                amt_sat=amount_sat,
                budget_sat=budget_sat,
                dry=dry
            )

            # Let LND update its balances.
            time.sleep(SLEEP_SEC_AFTER_REBALANCING)

            graph_after = self.testnet.assemble_graph()

            self.assertEqual(expected_fees_msat, fees_msat)

            # Check that we send the amount we wanted and that it's conserved.
            # TODO: This depends on channel reserves, we assume we opened the
            # channels.
            sent = 0
            received = 0
            for c in channel_numbers_send:
                sent += (graph_before['A'][c]['local_balance'] -
                    graph_after['A'][c]['local_balance'])

            for c in channel_numbers_receive:
                received += (graph_before['A'][c]['remote_balance'] -
                    graph_after['A'][c]['remote_balance'])

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

    def test_success_1_2(self):
        """Test successful rebalance from channel 1 to channel 2.

        Successful route: A->B->C->A.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 10_000
        expected_fees_msat = 43

        asyncio.run(self.circular_rebalance_and_check(
            channel_numbers_from,
            channel_numbers_to,
            amount_sat,
            expected_fees_msat
        ))

    def test_fail_1_2(self):
        """Test failing rebalance from channel 1 to channel 2.

        Route A->B->C->A fails because of missing liquidity from C->A.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 600_000

        self.assertRaises(
            NoRoute,
            lambda: asyncio.run(self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                None,
            ),
        ))

    def test_success_1_6(self):
        """Test successful rebalance from channel 1 to channel 6.

        Successful route: A->B->D->A.
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

    def test_6_1_fail_rebalance_failure_no_funds(self):
        """Test expected failure for channel 6 to channel 1, where channel 6
        doesn't have funds.
        """
        channel_numbers_from = [6]
        channel_numbers_to = [1]
        amount_sat = 10000
        expected_fees_msat = 33

        self.assertRaises(
            NoRoute,
            asyncio.run,
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat
            )
        )

    def test_1_6_fail_budget_too_expensive(self):
        """Test expected failure where rebalance uses more than the fee budget.
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

    def test_1_6_fail_max_fee_rate_too_expensive(self):
        """Test expected failure where rebalance is more expensive than
        the desired maximal fee rate.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        amount_sat = 10000
        expected_fees_msat = 33
        budget = 20
        max_effective_fee_rate = 0

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

    def test_1_6_success_channel_reserve(self):
        """Test for a maximal amount circular payment.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [6]
        local_balance = 1_000_000
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

    def test_1_6_fail_rebalance_dry(self):
        """Test if dry run exception is raised.
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

    def test_multi_send(self):
        """Tests sending over multiple rebalance candidates."""
        channel_numbers_from = [1, 2]
        channel_numbers_to = [6]
        amount_sat = 10000
        expected_fees_msat = 33

        asyncio.run(
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
            )
        )

    def test_multi_receive(self):
        """Tests receiving via multiple rebalance candidates."""
        channel_numbers_from = [1]
        channel_numbers_to = [2, 6]
        amount_sat = 10000
        expected_fees_msat = 33

        asyncio.run(
            self.circular_rebalance_and_check(
                channel_numbers_from,
                channel_numbers_to,
                amount_sat,
                expected_fees_msat,
            )
        )

class TestCircleIlliquid(CircleTest):
    network_definition = test_graphs_paths['star_ring_4_illiquid']

    def graph_test(self):
        self.assertEqual(10, len(self.master_node_graph_view))

    def test_fail_2_3_no_route(self):
        """Test that NoRoute is raised. We can't go beyond C, none of its
        channels have enough capacity.
        """
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

    def test_1_2_fail_max_trials_exhausted(self):
        """Test if RebalancingTrialsExhausted is raised.

        There will be a single rebalancing attempt A->B->C->A, which fails for
        B->C. After this trial we stop due to max rebalance trials.
        """
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 190950
        expected_fees_msat = None

        try:
            previous = settings.REBALANCING_TRIALS
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
        finally:
            settings.REBALANCING_TRIALS = previous

    def test_1_2_fail_no_route_multi_trials(self):
        """Test if RebalancingTrialsExhausted is raised.

        None of those paths support the payment:
        A -> B -> C -> A
        A -> B -> E -> C -> A
        A -> B -> D -> C -> A
        """
        channel_numbers_from = [1]
        channel_numbers_to = [2]
        amount_sat = 450000
        expected_fees_msat = None

        try:
            previous = settings.REBALANCING_TRIALS
            settings.REBALANCING_TRIALS = 3

            asyncio.run(
                self.circular_rebalance_and_check(
                    channel_numbers_from,
                    channel_numbers_to,
                    amount_sat,
                    expected_fees_msat,
                )
            )
        except RebalancingTrialsExhausted as e:
            self.assertEqual(4, e.trials)
        finally:
            settings.REBALANCING_TRIALS = previous

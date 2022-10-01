"""Integration tests for rebalancing of channels."""
import asyncio
import time
from typing import Optional

from test.testing_common import (
    test_graphs_paths,
    SLEEP_SEC_AFTER_REBALANCING,
    TestNetwork
)

from lndmanage.lib.rebalance import Rebalancer
from lndmanage.lib.ln_utilities import local_balance_to_unbalancedness
from lndmanage.lib.exceptions import NoRebalanceCandidates


class RebalanceTest(TestNetwork):
    """Implements an abstract testing class for channel rebalancing."""
    async def rebalance_and_check(
            self,
            test_channel_number: int,
            target: Optional[float],
            amount_sat: Optional[int],
            allow_uneconomic: bool,
            places: int = 5,
    ):
        """Test function for rebalancing to a specific target unbalancedness and
        asserts afterwards that the target was reached.

        :param test_channel_number: channel id
        :param target: unbalancedness target
        :param amount_sat: rebalancing amount
        :param allow_uneconomic: if uneconomic rebalancing should be allowed
        :param places: accuracy of the comparison between expected and tested
            values
        """
        async with self.lndnode:
            graph_before = self.testnet.assemble_graph()

            rebalancer = Rebalancer(
                self.lndnode,
                max_effective_fee_rate=5E-6,
                budget_sat=20,
                force=allow_uneconomic,
            )

            channel_id = self.testnet.channel_mapping[
                test_channel_number]['channel_id']

            fees_msat = rebalancer.rebalance(
                channel_id,
                dry=False,
                target=target,
                amount_sat=amount_sat,
            )

            # sleep a bit to let LNDs update their balances
            time.sleep(SLEEP_SEC_AFTER_REBALANCING)

            # check if graph has the desired channel balances
            graph_after = self.testnet.assemble_graph()

            channel_data_before = graph_before['A'][test_channel_number]
            channel_data_after = graph_after['A'][test_channel_number]
            amount_sent = (channel_data_before['local_balance'] -
                               channel_data_after['local_balance'])

            channel_unbalancedness, _ = local_balance_to_unbalancedness(
                channel_data_after['local_balance'],
                channel_data_after['capacity'],
                channel_data_after['commit_fee'],
                channel_data_after['initiator']
            )

            if target is not None:
                self.assertAlmostEqual(
                    target, channel_unbalancedness, places=places)

            elif amount_sat is not None:
                self.assertAlmostEqual(
                    amount_sat, amount_sent, places=places)

            return fees_msat

    def graph_test(self):
        """graph_test should be implemented by each subclass test and check,
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
        self.assertEqual(6, len(self.master_node_graph_view))

    def test_non_init_balanced(self):
        test_channel_number = 6
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=0.0,
                amount_sat=None,
                allow_uneconomic=True
            )
        )

    def test_non_init_small_positive_target(self):
        test_channel_number = 6
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=0.2,
                amount_sat=None,
                allow_uneconomic=True
            )
        )

    def test_non_init_max_target(self):
        test_channel_number = 6
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=1.0,
                amount_sat=None,
                allow_uneconomic=True
            )
        )

    def test_non_init_negative_target(self):
        # this test should fail when unbalancing is not allowed, as it would
        # unbalance another channel if the full target would be accounted for
        test_channel_number = 6
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=-0.2,
                amount_sat=None,
                allow_uneconomic=True
            )
        )

    def test_non_init_fail_due_to_economic(self):
        # this test should fail when unbalancing is not allowed, as it would
        # unbalance another channel if the full target would be accounted for
        test_channel_number = 6
        self.assertRaises(
            NoRebalanceCandidates,
            asyncio.run,
            self.rebalance_and_check(
                test_channel_number,
                target=-0.2,
                amount_sat=None,
                allow_uneconomic=False
            )
        )

    def test_init_balanced(self):
        test_channel_number = 1
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=0.0,
                amount_sat=None,
                allow_uneconomic=True,
                places=1
            )
        )

    def test_init_already_balanced(self):
        test_channel_number = 2
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=0.0,
                amount_sat=None,
                allow_uneconomic=True,
                places=2
            )
        )

    def test_init_default_amount(self):
        test_channel_number = 1
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=None,
                amount_sat=None,
                allow_uneconomic=True,
                places=-1
            )
        )

    def test_shuffle_arround(self):
        """Shuffles sats around in channel 6."""
        first_target_amount = -0.1
        second_target_amount = 0.1
        test_channel_number = 6

        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=first_target_amount,
                amount_sat=None,
                allow_uneconomic=True
            )
        )
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=second_target_amount,
                amount_sat=None,
                allow_uneconomic=True
            )
        )


class TestUnbalancedRebalance(RebalanceTest):
    network_definition = test_graphs_paths['star_ring_4_unbalanced']

    # channels:
    # A -> B (channel #1)
    # A -> C (channel #2)
    # A -> D (channel #3)
    # A -> E (channel #4)

    def graph_test(self):
        self.assertEqual(10, len(self.master_node_graph_view))

    def test_channel_1(self):
        """tests multiple rebalance of one channel"""
        test_channel_number = 1
        asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=-0.05,
                amount_sat=None,
                allow_uneconomic=True,
                places=1
            )
        )


class TestIlliquidRebalance(RebalanceTest):
    network_definition = test_graphs_paths['star_ring_4_illiquid']

    # channels:
    # A -> B (channel #1)
    # A -> C (channel #2)
    # A -> D (channel #3)
    # A -> E (channel #4)

    def graph_test(self):
        self.assertEqual(10, len(self.master_node_graph_view))

    def test_channel_1_splitting(self):
        """Tests multiple payment attempts with splitting."""
        test_channel_number = 1 #
        fees_msat = asyncio.run(
            self.rebalance_and_check(
                test_channel_number,
                target=-0.05,
                amount_sat=None,
                allow_uneconomic=True,
                places=1
            )
        )
        self.assertAlmostEqual(2000, fees_msat, places=-3)

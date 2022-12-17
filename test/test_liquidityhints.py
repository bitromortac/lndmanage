from dataclasses import dataclass
from unittest import TestCase, mock

from lndmanage.lib.data_types import NodePair
from lndmanage.lib.liquidityhints import LiquidityHintMgr, AmountHistory, LiquidityHint


@dataclass
class MCPairHistory:
    fail_amt_msat: int
    success_amt_msat: int
    fail_time: int = 0
    success_time: int = 0


@dataclass
class MCPair:
    node_from: bytes
    node_to: bytes
    history: MCPairHistory


class LiquidityTest(TestCase):

    @mock.patch('time.time', mock.MagicMock(return_value=100))
    def test_load_mission_control(self):
        mgr = LiquidityHintMgr("pubkey")

        pairs = [
            # valid pair
            MCPair(
                node_from=bytes.fromhex("aa"),
                node_to=bytes.fromhex("bb"),
                history=MCPairHistory(
                    success_amt_msat=10000,
                    success_time=1,  # to be considered a valid hint
                    fail_amt_msat=30000,
                    fail_time=1,  # to be considered a valid hint
                )
            ),
            # invalid pair (no timestamps)
            MCPair(
                node_from=bytes.fromhex("bb"),
                node_to=bytes.fromhex("cc"),
                history=MCPairHistory(
                    fail_amt_msat=30000,
                    success_amt_msat=10000,
                )
            )
        ]
        mgr.extend_with_mission_control(pairs)

        node_pair = NodePair(("aa", "bb"))
        hint = mgr._liquidity_hints.get(node_pair)
        # hint from mc:
        self.assertEqual(
            AmountHistory(amount_msat=10000, timestamp=1),
            hint.can_send("aa" > "bb"),
        )
        # hint from mc:
        self.assertEqual(
            AmountHistory(amount_msat=30000, timestamp=1),
            hint.cannot_send("aa" > "bb"),
        )
        # we conclude for the backward direction from the failure:
        self.assertEqual(
            AmountHistory(),
            hint.can_send("bb" > "aa"),
        )
        # we can't say anything about the amount that cannot be sent in the backward
        # direction
        self.assertEqual(
            AmountHistory(),
            hint.cannot_send("bb" > "aa"),
        )

        node_pair = NodePair(("bb", "cc"))
        hint = mgr._liquidity_hints.get(node_pair)
        self.assertIsNone(hint)

class TestLiquidityHint(TestCase):
    def test_liquidity_hint(self):
        """Test updating an expired hint."""

        hint = LiquidityHint()
        amount = 100000000
        direction = False
        self.assertFalse(direction)

        hint = LiquidityHint()
        hint._can_send_backward = AmountHistory(None, None)
        hint._can_send_forward = AmountHistory(100066910, 0)
        hint._cannot_send_backward = AmountHistory(25003625, 0)
        hint._cannot_send_forward = AmountHistory(100066911, 0)

        self.assertIsNone(hint.can_send(direction).amount_msat)
        self.assertIsNone(hint.cannot_send(direction).amount_msat)

        hint.update_cannot_send(direction, amount, None)

        self.assertIsNone(hint.can_send(direction).amount_msat)
        self.assertEqual(amount, hint.cannot_send(direction).amount_msat)


"""Integration tests for batch opening of channels."""
import asyncio
import time
from unittest import TestCase

from lndmanage.lib import openchannels

from test.testing_common import (
    test_graphs_paths,
    TestNetwork,
)


def confirm_transactions(testnet):
    for _ in range(6):
        testnet.bitcoind.mine_blocks(1)
        time.sleep(0.2)


class Batchopen(TestNetwork):
    """Tests batched channel opening."""

    network_definition = test_graphs_paths['star_ring_3_liquid']

    def graph_test(self):
        self.assertEqual(6, len(self.master_node_graph_view))

    def test_batchopen(self):
        channel_opener = openchannels.ChannelOpener(self.lndnode)
        channel_partner_pubkeys = [self.testnet.ln_nodes['B'], self.testnet.ln_nodes['C']]

        # prepare user input
        pubkey_input = ",".join([
            channel_partner.pubkey for channel_partner in channel_partner_pubkeys
        ])

        async def run_tests():
            async with self.lndnode:
                with self.subTest(msg="(implicit), using amounts, change created, high fees"):
                    amount1 = 111_111
                    amount2 = 222_222

                    wallet_utxos_before = self.lndnode.get_utxos()
                    channels_before = self.lndnode.get_open_channels()
                    channel_opener.open_channels(
                        pubkeys=pubkey_input,
                        amounts=f"{amount1},{amount2}",
                        reckless=True,
                        sat_per_vbyte=20,
                    )
                    confirm_transactions(self.testnet)
                    wallet_utxos_after = self.lndnode.get_utxos()
                    channels_after = self.lndnode.get_open_channels()

                    self.assertEqual(2, len(channels_after) - len(channels_before))
                    self.assertEqual(0, len(wallet_utxos_before) - len(wallet_utxos_after))

                    channel_capacities_after = [channel['capacity'] for channel in channels_after.values()]
                    self.assertIn(amount1, channel_capacities_after)
                    self.assertIn(amount2, channel_capacities_after)

                with self.subTest(msg="(implicit), total amount, private, change created"):
                    total_amount = 4_444_444

                    wallet_utxos_before = self.lndnode.get_utxos()
                    channels_before = self.lndnode.get_open_channels()
                    channel_opener.open_channels(
                        pubkeys=pubkey_input,
                        total_amount=total_amount,
                        reckless=True,
                        private=True,
                    )
                    confirm_transactions(self.testnet)
                    wallet_utxos_after = self.lndnode.get_utxos()
                    channels_after = self.lndnode.get_open_channels()

                    self.assertEqual(2, len(channels_after) - len(channels_before))
                    self.assertEqual(0, len(wallet_utxos_before) - len(wallet_utxos_after))

                    total_capacity_before = sum([channel['capacity'] for channel in channels_before.values()])
                    total_capacity_after = sum([channel['capacity'] for channel in channels_after.values()])
                    self.assertEqual(total_amount, total_capacity_after - total_capacity_before)
                    num_private_channels = len([True for v in channels_after.values() if v['private']])
                    self.assertEqual(2, num_private_channels)

                with self.subTest(msg="(explicit), spend fully, no change created"):
                    address = self.testnet.master_node.getaddress()
                    self.testnet.bitcoind.sendtoaddress(address, 0.10_000_000)
                    confirm_transactions(self.testnet)

                    wallet_utxos_before = self.lndnode.get_utxos()
                    channels_before = self.lndnode.get_open_channels()
                    # maybe make sure we select the correct utxo
                    spent_utxo = wallet_utxos_before[0]
                    utxo_input = f"{spent_utxo.txid}:{spent_utxo.output_index}"
                    channel_opener.open_channels(
                        utxos=utxo_input,
                        pubkeys=pubkey_input,
                        reckless=True,
                    )
                    confirm_transactions(self.testnet)
                    wallet_utxos_after = self.lndnode.get_utxos()
                    channels_after = self.lndnode.get_open_channels()

                    self.assertEqual(2, len(channels_after) - len(channels_before))
                    self.assertEqual(1, len(wallet_utxos_before) - len(wallet_utxos_after))

                    self.assertNotIn(spent_utxo, wallet_utxos_after)

                # clear wallet, but keep anchor reserves, leaves 50000 sat
                self.testnet.master_node.rpc(["sendcoins", "--sweepall", "bcrt1qs758ursh4q9z627kt3pp5yysm78ddny6txaqgw"])
                confirm_transactions(self.testnet)

                with self.subTest(msg="implicit coins, relative amounts, anchor reserve created"):
                    address = self.testnet.master_node.getaddress()
                    self.testnet.bitcoind.sendtoaddress(address, 0.10_000_000)
                    confirm_transactions(self.testnet)

                    wallet_utxos_before = self.lndnode.get_utxos()
                    channels_before = self.lndnode.get_open_channels()
                    channel_opener.open_channels(
                        amounts="1,2",
                        pubkeys=pubkey_input,
                        reckless=True,
                    )
                    confirm_transactions(self.testnet)
                    wallet_utxos_after = self.lndnode.get_utxos()
                    channels_after = self.lndnode.get_open_channels()

                    self.assertEqual(2, len(channels_after) - len(channels_before))
                    self.assertEqual(1, len(wallet_utxos_before) - len(wallet_utxos_after))

                    wallet_utxo_amounts = [utxo.amount_sat for utxo in wallet_utxos_after]
                    self.assertIn(openchannels.ANCHOR_RESERVE, wallet_utxo_amounts)

                with self.subTest(msg="implicit coins, nested-P2WKH, too large amounts"):
                    amount1 = 5_000_000
                    amount2 = 6_000_000
                    address = self.testnet.master_node.getaddress(address_type='np2wkh')
                    self.testnet.bitcoind.sendtoaddress(address, 0.10_000_000)
                    confirm_transactions(self.testnet)

                    wallet_utxos_before = self.lndnode.get_utxos()
                    channels_before = self.lndnode.get_open_channels()
                    channel_opener.open_channels(
                        amounts=f"{amount1},{amount2}",
                        pubkeys=pubkey_input,
                        reckless=True,
                    )
                    confirm_transactions(self.testnet)
                    wallet_utxos_after = self.lndnode.get_utxos()
                    channels_after = self.lndnode.get_open_channels()

                    self.assertEqual(2, len(channels_after) - len(channels_before))
                    self.assertEqual(1, len(wallet_utxos_before) - len(wallet_utxos_after))

                    total_capacity_before = sum([channel['capacity'] for channel in channels_before.values()])
                    total_capacity_after = sum([channel['capacity'] for channel in channels_after.values()])
                    # test that we have reduced the amounts
                    self.assertGreater(amount1 + amount2, total_capacity_after - total_capacity_before)

                with self.subTest(msg="implicit coins, nested-P2WKH, too large amounts"):
                    address = self.testnet.master_node.getaddress(address_type='np2wkh')
                    self.testnet.bitcoind.sendtoaddress(address, 0.10_000_000)
                    confirm_transactions(self.testnet)
                    total_amount = 20_000_000
                    wallet_utxos_before = self.lndnode.get_utxos()
                    channels_before = self.lndnode.get_open_channels()
                    channel_opener.open_channels(
                        total_amount=total_amount,
                        pubkeys=pubkey_input,
                        reckless=True,
                    )
                    confirm_transactions(self.testnet)
                    wallet_utxos_after = self.lndnode.get_utxos()
                    channels_after = self.lndnode.get_open_channels()

                    self.assertEqual(2, len(channels_after) - len(channels_before))
                    self.assertEqual(1, len(wallet_utxos_before) - len(wallet_utxos_after))

                    total_capacity_before = sum([channel['capacity'] for channel in channels_before.values()])
                    total_capacity_after = sum([channel['capacity'] for channel in channels_after.values()])
                    # test that we have reduced the total amount
                    self.assertGreater(total_amount, total_capacity_after - total_capacity_before)

                with self.subTest(msg="implicit coins, full spend, wumbo violation"):
                    address = self.testnet.master_node.getaddress()
                    self.testnet.bitcoind.sendtoaddress(address, (2 * openchannels.WUMBO_LIMIT + 1000) * 1E-8)

                    confirm_transactions(self.testnet)
                    self.assertRaises(
                        ValueError, channel_opener.open_channels,
                        pubkeys=pubkey_input,
                        reckless=True,
                    )
        asyncio.run(run_tests())


class FeeTest(TestCase):
    def test_fee_estimation(self):
        self.assertNotEqual(165, openchannels.calculate_fees(sat_per_vbyte=1, num_p2wkh_inputs=1, num_np2wkh_inputs=0, num_channels=2, has_change=False))
        self.assertNotEqual(196, openchannels.calculate_fees(sat_per_vbyte=1, num_p2wkh_inputs=1, num_np2wkh_inputs=0, num_channels=2, has_change=True))
        self.assertEqual(227, openchannels.calculate_fees(sat_per_vbyte=1, num_p2wkh_inputs=1, num_np2wkh_inputs=0, num_channels=2, has_change=True))  # reproduce bug in lnd
        self.assertEqual(196, openchannels.calculate_fees(sat_per_vbyte=1, num_p2wkh_inputs=1, num_np2wkh_inputs=0, num_channels=2, has_change=False))  # reproduce bug in lnd

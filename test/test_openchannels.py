"""
Integration tests for batch opening of channels.
"""
import time
from unittest import TestCase

from lndmanage import settings
from lndmanage.lib import openchannels

from test.testnetwork import TestNetwork

from test.testing_common import (
    lndmanage_home,
    test_graphs_paths,
)

import logging.config

settings.set_lndmanage_home_dir(lndmanage_home)
logging.config.dictConfig(settings.logger_config)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.handlers[0].setLevel(logging.DEBUG)


def confirm_channels(testnet):
    for _ in range(6):
        testnet.bitcoind.mine_blocks(1)
        time.sleep(0.1)


class Batchopen(TestNetwork):
    """
    Tests batch channel opening.
    """
    network_definition = test_graphs_paths['star_ring_3_liquid']

    def graph_test(self):
        self.assertEqual(4, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(6, self.master_node_networkinfo['num_channels'])

    def test_batchopen(self):
        with self.subTest(msg="using all utxos, using amounts"):
            channel_opener = openchannels.ChannelOpener(self.lndnode)
            channel_partner_pubkeys = [self.testnet.ln_nodes['B'], self.testnet.ln_nodes['C']]
            channel_capacities = [100000, 300000]

            # prepare user input
            pubkey_input = ",".join([
                channel_partner.pubkey for channel_partner in channel_partner_pubkeys
            ])
            amounts_input = ",".join([str(c) for c in channel_capacities])

            channel_opener.open_channels(
                pubkeys=pubkey_input,
                amounts=amounts_input,
                utxos=None,
                reckless=True
            )
            confirm_channels(self.testnet)
            self.assertEqual(5, len(self.lndnode.get_all_channels().keys()))

        with self.subTest(msg="using all utxos, using total amount"):
            channel_opener.open_channels(
                pubkeys=pubkey_input,
                amounts=None,
                utxos=None,
                reckless=True,
                total_amount=1_000_000,
            )
            confirm_channels(self.testnet)
            self.assertEqual(7, len(self.lndnode.get_all_channels().keys()))

        with self.subTest(msg="using single utxo, using total amount"):
            wallet_utxos_before = self.lndnode.get_utxos()
            logger.info(wallet_utxos_before)
            spent_utxo = list(wallet_utxos_before.keys())[0]
            utxo_input = f"{spent_utxo[0]}:{spent_utxo[1]}"

            channel_opener.open_channels(
                pubkeys=pubkey_input,
                amounts=None,
                reckless=True,
                total_amount=1_000_000,
                utxos=utxo_input
            )
            confirm_channels(self.testnet)
            self.assertEqual(9, len(self.lndnode.get_all_channels().keys()))

        with self.subTest(msg="having two utxos, using one of them, open two channels with amounts, test for unused utxo"):
            address = self.testnet.master_node.getaddress()
            self.testnet.bitcoind.sendtoaddress(address, 0.1)
            self.testnet.bitcoind.mine_blocks(6)
            time.sleep(1)
            wallet_utxos_before = self.lndnode.get_utxos()
            assert len(wallet_utxos_before) == 2
            spent_utxo = list(wallet_utxos_before.keys())[0]
            unspent_utxo = list(wallet_utxos_before.keys())[1]
            utxo_input = f"{spent_utxo[0]}:{spent_utxo[1]}"

            channel_opener.open_channels(
                pubkeys=pubkey_input,
                amounts=amounts_input,
                reckless=True,
                utxos=utxo_input
            )
            confirm_channels(self.testnet)
            wallet_utxos_after = self.lndnode.get_utxos()
            assert unspent_utxo in wallet_utxos_after.keys()
            assert len(wallet_utxos_after) == 2

        with self.subTest(msg="having two utxos, using one of them, open two channels with too high amounts"):
            wallet_utxos_before = self.lndnode.get_utxos()
            spent_utxo = list(wallet_utxos_before.keys())[0]
            utxo_input = f"{spent_utxo[0]}:{spent_utxo[1]}"
            amounts_input = "6000000,7000000"
            channel_opener.open_channels(
                pubkeys=pubkey_input,
                total_amount=None,
                reckless=True,
                utxos=utxo_input,
                amounts=amounts_input,
            )
            confirm_channels(self.testnet)
            wallet_utxos_after = self.lndnode.get_utxos()
            print(wallet_utxos_after)

        with self.subTest(msg="having one utxo, open two channels with two relative amounts (< 100)"):
            wallet_utxos_before = self.lndnode.get_utxos()
            logger.info(wallet_utxos_before)
            spent_utxo = list(wallet_utxos_before.keys())[0]
            utxo_input = f"{spent_utxo[0]}:{spent_utxo[1]}"
            amounts_input = "1,2"
            channel_opener.open_channels(
                pubkeys=pubkey_input,
                total_amount=None,
                reckless=True,
                utxos=utxo_input,
                amounts=amounts_input,
            )
            confirm_channels(self.testnet)
            wallet_utxos_after = self.lndnode.get_utxos()
            assert len(wallet_utxos_after) == 0

        with self.subTest(msg="open two private channels"):
            self.testnet.nodes_fill_wallets()
            time.sleep(1)
            channel_opener.open_channels(
                pubkeys=pubkey_input,
                total_amount=None,
                reckless=True,
                amounts=amounts_input,
                private=True
            )
            confirm_channels(self.testnet)
            self.lndnode.get_open_channels()
            private_channels = [k for k, v in self.lndnode.get_open_channels().items() if v['private']]
            print(private_channels)
            assert len(private_channels) == 2

class FeeTest(TestCase):
    def test_fee_estimation(self):
        self.assertEqual(277, openchannels.calculate_fees(sat_per_byte=1, number_inputs=1, number_channels=2, change=True))
        self.assertEqual(246, openchannels.calculate_fees(sat_per_byte=1, number_inputs=1, number_channels=2, change=False))

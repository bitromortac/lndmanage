"""
Tests lndmanaged, lnd management daemon.
"""
import asyncio
from typing import TYPE_CHECKING
from configparser import ConfigParser
from unittest.mock import patch

from lndmanage.lib.chan_acceptor import ChanAcceptor
from lndmanage import settings
from test.testnetwork import TestNetwork

from test.testing_common import (
    test_graphs_paths,
    lndmanage_home,
)

if TYPE_CHECKING:
    from lnregtest.lib.network_components import LND

import logging.config
settings.set_lndmanage_home_dir(lndmanage_home)
logging.config.dictConfig(settings.lndm_logger_config)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.handlers[0].setLevel(logging.DEBUG)


def cancel_all_tasks_callback(future: asyncio.Future):
    logger.debug(f"TEST: Task {future} is done, cleaning up other tasks.")
    for t in asyncio.all_tasks():
        t.cancel()


async def async_open_channel(opener_node: 'LND', pubkey: str, local_sat: int,
                             remote_sat: int):
        info = await opener_node._a_openchannel(pubkey, local_sat, remote_sat)
        return info


def was_channel_accepted_helper(chan_acceptor, loop, node_id_from, node_id_to,
                          local_sat, remote_sat) -> bool:
    # accept: test channel open
    open_task = async_open_channel(
        node_id_from,
        node_id_to,
        local_sat,
        remote_sat,
    )
    acceptor_task = loop.create_task(
        chan_acceptor.manage_channel_openings())
    open_task = loop.create_task(open_task)
    # callback to cancel acceptor
    open_task.add_done_callback(cancel_all_tasks_callback)
    results = loop.run_until_complete(asyncio.gather(acceptor_task, open_task))

    if results[1] == '':  # channel open failed
        return False
    elif len(results[1]['funding_txid']) == 64:  # channel open succeeded
        return True


class LndmanagedTest(TestNetwork):
    network_definition = test_graphs_paths['star_ring_3_liquid']

    def graph_test(self):
        # assert some basic properties of the graph
        self.assertEqual(4, self.master_node_networkinfo['num_nodes'])
        self.assertEqual(6, self.master_node_networkinfo['num_channels'])

    def test_channel_acceptor(self):
        """Tests accepting and rejecting of channels."""
        config = ConfigParser()
        chan_acceptor = ChanAcceptor(self.lndnode, config)

        # set up two cases, one for private connecting nodes and one for
        # public connecting nodes
        # private:
        chan_acceptor.min_size_private = 0
        chan_acceptor.max_size_private = 2_000_000
        # public:
        chan_acceptor.min_size_public = 4_000_000
        master_node_id = self.testnet.node_mapping['A']

        with patch.object(chan_acceptor.network_analysis, 'is_private') as mock:
            # PRIVATE NODES
            mock.return_value = True

            accepted = was_channel_accepted_helper(
                chan_acceptor,
                self.lndnode.loop,
                self.testnet.ln_nodes['B'],
                master_node_id,
                local_sat=1_000_000,
                remote_sat=0,
            )
            self.assertTrue(accepted)

            accepted = was_channel_accepted_helper(
                chan_acceptor,
                self.lndnode.loop,
                self.testnet.ln_nodes['C'],
                master_node_id,
                local_sat=3_000_000,
                remote_sat=0,
            )
            self.assertFalse(accepted)

            # PUBLIC NODES
            mock.return_value = False

            accepted = was_channel_accepted_helper(
                chan_acceptor,
                self.lndnode.loop,
                self.testnet.ln_nodes['C'],
                master_node_id,
                local_sat=3_000_000,
                remote_sat=0,
            )
            self.assertFalse(accepted)


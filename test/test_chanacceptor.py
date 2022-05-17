"""Tests for channel acceptor."""
import asyncio
from typing import TYPE_CHECKING
from configparser import ConfigParser
from unittest.mock import patch

from lndmanage.lib.chan_acceptor import ChanAcceptor

from test.testing_common import (
    test_graphs_paths,
    TestNetwork,
    logger,
)

if TYPE_CHECKING:
    from lnregtest.lib.network_components import LND


def cancel_all_tasks_callback(future: asyncio.Future):
    logger.debug(f"TEST: Task {future} is done, cleaning up other tasks.")
    for t in asyncio.all_tasks():
        t.cancel()


async def async_open_channel(opener_node: 'LND', pubkey: str, local_sat: int,
                             remote_sat: int):
    info = await opener_node._a_openchannel(pubkey, local_sat, remote_sat)
    return info


async def channel_accepted(
        lndnode,
        chan_acceptor,
        node_id_from,
        node_id_to,
        local_sat,
        remote_sat
) -> bool:

    async with lndnode:
        open_task = asyncio.create_task(async_open_channel(
            node_id_from,
            node_id_to,
            local_sat,
            remote_sat,
        ))
        acceptor_task = asyncio.create_task(
            chan_acceptor.accept_channels())

        tasks = [open_task, acceptor_task]

        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        result = None
        for task in tasks:
            if not task.done():
                task.cancel()
            else:
                result = task.result()

        if result == '':  # channel open failed
            return False
        elif len(result['funding_txid']) == 64:  # channel open succeeded
            return True
        elif None:
            raise Exception("test didn't work")


class LndmanagedTest(TestNetwork):
    network_definition = test_graphs_paths['star_ring_3_liquid']

    def graph_test(self):
        # assert some basic properties of the graph
        self.assertEqual(6, len(self.testnet.master_node_graph_view()))

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
        chan_acceptor.max_size_public = 4_000_000
        master_node_id = self.testnet.node_mapping['A']

        # We mock the private/public nature of opened channels.
        with patch.object(chan_acceptor.network_analysis, 'is_private') as mock:
            # Private nodes
            mock.return_value = True

            accepted = asyncio.run(channel_accepted(
                self.lndnode,
                chan_acceptor,
                self.testnet.ln_nodes['B'],
                master_node_id,
                local_sat=1_000_000,
                remote_sat=0,
            ))
            self.assertTrue(accepted)

            accepted = asyncio.run(channel_accepted(
                self.lndnode,
                chan_acceptor,
                self.testnet.ln_nodes['C'],
                master_node_id,
                local_sat=3_000_000,
                remote_sat=0,
            ))
            self.assertFalse(accepted)

            # Public nodes
            mock.return_value = False

            accepted = asyncio.run(channel_accepted(
                self.lndnode,
                chan_acceptor,
                self.testnet.ln_nodes['C'],
                master_node_id,
                local_sat=3_000_000,
                remote_sat=0,
            ))
            self.assertTrue(accepted)

"""Implements logic for accepting channels dynamically."""
import asyncio
from typing import TYPE_CHECKING

from lndmanage.grpc_compiled import rpc_pb2 as lnd
from lndmanage.lib.node import LndNode
from lndmanage import settings
from lndmanage.lib.network_info import NetworkAnalysis

import logging
logger = logging.getLogger('CHANAC')
logger.setLevel(logging.DEBUG)

if TYPE_CHECKING:
    from configparser import ConfigParser


class ChanAcceptor(object):
    min_size_private: int
    max_size_private: int
    min_size_public: int
    max_size_public: int

    def __init__(self, node: LndNode, config: 'ConfigParser'):
        self.node = node
        self.config = config
        self.network_analysis = NetworkAnalysis(self.node)
        self.configure()

    def configure(self):
        # configuration is designed to also accept an empty configuration,
        # in which case we take default values as fallback
        self.min_size_private = int(
            self.config.get(
                'channel_acceptor',
                'min_channel_size_private',
                fallback=settings.CHACC_MIN_CHANNEL_SIZE_PRIVATE
            )
        )
        self.max_size_private = int(
            self.config.get(
                'channel_acceptor',
                'max_channel_size_private',
                fallback=settings.CHACC_MAX_CHANNEL_SIZE_PRIVATE
            )
        )
        self.min_size_public = int(
            self.config.get(
                'channel_acceptor',
                'min_channel_size_public',
                fallback=settings.CHACC_MIN_CHANNEL_SIZE_PUBLIC
            )
        )
        self.max_size_public = int(
            self.config.get(
                'channel_acceptor',
                'max_channel_size_public',
                fallback=settings.CHACC_MAX_CHANNEL_SIZE_PUBLIC
            )
        )

    async def manage_channel_openings(self):
        response_queue = asyncio.queues.Queue()
        try:
            # async way to use a bidirectional streaming grpc endpoint
            # with an async iterator
            async for r in self.node.async_rpc.ChannelAcceptor(
                    self.request_iterator(response_queue)):
                await response_queue.put(r)
        except asyncio.CancelledError:
            logger.info("channel acceptor cancelled")
            return

    async def request_iterator(self, channel_details: asyncio.Queue):
        logger.info("channel acceptor started")
        while True:
            channel_detail = await channel_details.get()
            if self.accept_channel(channel_detail):
                yield lnd.ChannelAcceptResponse(
                    accept=True, pending_chan_id=channel_detail.pending_chan_id
                )
            else:
                yield lnd.ChannelAcceptResponse(
                    accept=False, pending_chan_id=channel_detail.pending_chan_id
                )

    def accept_channel(self, channel_detail) -> bool:
        # be careful, exceptions from here seem to not get raised up to the main
        # loop
        # TODO: raise exceptions from here
        logger.info(
            f"about to make a decision about channel:\n{channel_detail}")
        node_pubkey = channel_detail.node_pubkey.hex()
        is_private = self.network_analysis.is_private(node_pubkey)
        logger.info(f"is private {is_private}")
        if is_private:
            if (self.min_size_private < channel_detail.funding_amt
                    < self.max_size_private):
                return True
        else:
            if (self.min_size_public < channel_detail.funding_amt
                    < self.max_size_public):
                return True
        return False

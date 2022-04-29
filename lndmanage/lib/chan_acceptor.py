"""Implements logic for accepting channels dynamically."""
import asyncio
from typing import TYPE_CHECKING
import textwrap

import lndmanage.grpc_compiled.lightning_pb2 as lnd

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

    async def accept_channels(self):
        logger.info("Channel acceptor started.")
        response_queue = asyncio.queues.Queue()

        # Use an async bidirectional streaming grpc endpoint with an async iterator.
        # Note: no exceptions escape from there, handle them inside the iterator.
        async for r in self.node.async_rpc.ChannelAcceptor(
                self.request_iterator(response_queue)):
            if isinstance(r, Exception):
                raise r
            await response_queue.put(r)

    async def request_iterator(self, channel_details: asyncio.Queue):
        # Be careful, exceptions don't leave from here, only get logged.
        try:
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
        except asyncio.CancelledError:
            logger.info("canceled")

    def accept_channel(self, channel_detail) -> bool:
        logger.info(
            f"About to make a decision about a channel:")
        logger.info(textwrap.indent(str(channel_detail), "    "))

        node_pubkey = channel_detail.node_pubkey.hex()
        is_private = self.network_analysis.is_private(node_pubkey)

        # We apply different policies for private or public channels.
        if is_private:
            if (self.min_size_private < channel_detail.funding_amt
                    < self.max_size_private):
                logger.debug(f"Private channel accepted.")
                return True
        else:
            if (self.min_size_public < channel_detail.funding_amt
                    < self.max_size_public):
                logger.debug(f"Public channel accepted.")
                return True

        logger.debug(f"Channel open rejected.")
        return False
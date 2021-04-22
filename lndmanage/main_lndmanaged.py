"""Implements a daemon for constant watching of an LND node."""
import time
import asyncio
from signal import SIGINT, SIGTERM
from typing import Optional
import warnings
import os

from lndmanage.lib.node import LndNode
from lndmanage.lib.chan_acceptor import ChanAcceptor
import lndmanage.grpc_compiled.rpc_pb2 as lnd
import lndmanage.grpc_compiled.router_pb2 as lndrouter

from lndmanage import settings

import logging.config
logging.config.dictConfig(settings.lndmd_logger_config)
logger = logging.getLogger()

ASYNCIO_DEBUG = False


def handler(sig):
    """Handler for task cancelation upon kill signals."""
    loop = asyncio.get_running_loop()
    for task in asyncio.all_tasks(loop=loop):
        task.cancel()
    logger.debug(f'Got signal {sig!s}, shutting down.')
    loop.remove_signal_handler(SIGTERM)
    # protect from CTRL+C
    loop.add_signal_handler(SIGINT, lambda: None)


class LNDManageDaemon(object):
    def __init__(self, lndm_config_path: Optional[str] = None,
                 lndmd_config_path: Optional[str] = None,
                 lnd_home: Optional[str] = None,
                 lnd_host: Optional[str] = None,
                 regtest: bool = False):
        self.lndm_config_path = lndm_config_path
        self.lndmd_config_path = lndmd_config_path
        self.lnd_home = lnd_home
        self.lnd_host = lnd_host
        self.regtest = regtest
        self.node = LndNode(config_file=lndm_config_path, lnd_home=lnd_home,
                            lnd_host=lnd_host, regtest=regtest)
        self.config = settings.read_config(self.lndmd_config_path)

    @staticmethod
    async def service_alive_message():
        while True:
            await asyncio.sleep(10 * 60.0)
            logger.info(f"{time.time()} lndmanaged is running")

    async def service_graph_stream(self):
        """Logs graph updates."""
        graph_stream = self.node.async_rpc.SubscribeChannelGraph(
            lnd.GraphTopologySubscription())
        try:
            async for g in graph_stream:
                logger.info(g)
        except asyncio.CancelledError:
            logger.debug('graph_stream shutting down')

    async def service_htlc_stream(self):
        """Logs HTLC updates."""
        graph_stream = self.node.async_routerrpc.SubscribeHtlcEvents(
            lndrouter.SubscribeHtlcEventsRequest())
        try:
            async for g in graph_stream:
                logger.info(g)
        except asyncio.CancelledError:
            logger.debug('htlc_stream shutting down')
        # TODO: persist failed HTLCs

    async def service_channel_acceptor(self):
        """Handles channel opening requests."""
        channel_acceptor = ChanAcceptor(self.node, self.config)
        try:
            await channel_acceptor.manage_channel_openings()
        except asyncio.CancelledError:
            logger.debug('channel_acceptor shutting down')

    def run_services(self):
        """Main method to start registered services."""
        loop = self.node.loop
        if ASYNCIO_DEBUG:
            loop.set_debug(True)
            loop.slow_callback_duration = 0.01
            warnings.simplefilter('always', ResourceWarning)

        # register signal handler for process cancelation
        for sig in (SIGTERM, SIGINT):
            loop.add_signal_handler(sig, handler, sig)

        # run services
        try:
            services = asyncio.gather(
                self.service_channel_acceptor(),
                self.service_alive_message(),
                self.service_htlc_stream(),
                # self.service_graph_stream(),
            )
            loop.run_until_complete(services)
        except asyncio.CancelledError:
            logger.debug('main shutting down')
        except Exception as e:
            logger.exception("exception occured")
        finally:
            self.node.disconnect_rpcs()


def main():
    lndm_config_path = os.path.join(settings.home_dir, 'config.ini')
    lndmd_config_path = os.path.join(settings.home_dir, 'lndmanaged.ini')

    lndmd = LNDManageDaemon(
        lndm_config_path=lndm_config_path,
        lndmd_config_path=lndmd_config_path,
    )
    lndmd.run_services()


if __name__ == '__main__':
    lndmd = LNDManageDaemon(
        lndm_config_path="/home/user/.lndmanage/config.ini",
        lndmd_config_path="/home/user/.lndmanage/lndmanaged.ini")
    lndmd.run_services()

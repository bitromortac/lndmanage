"""Implements a daemon for constant watching of an LND node."""
import asyncio
import time
from signal import SIGINT, SIGTERM
from typing import Optional, Dict, Coroutine
import warnings

import grpc

from lndmanage.lib.node import LndNode
from lndmanage.lib.chan_acceptor import ChanAcceptor
import lndmanage.grpc_compiled.lightning_pb2 as lnd
import lndmanage.grpc_compiled.router_pb2 as lndrouter
import lndmanage.grpc_compiled.manager_pb2_grpc as manager_grpc
import lndmanage.grpc_compiled.manager_pb2 as manager

from lndmanage import settings

import logging.config
logging.config.dictConfig(settings.lndmanaged_log_config)
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
        self.running_services: Dict[str, Coroutine] = {}
        self.node = LndNode(config_file=lndm_config_path, lnd_home=lnd_home,
                            lnd_host=lnd_host, regtest=regtest)
        self.config = settings.read_config(self.lndmd_config_path)

    @staticmethod
    async def service_alive_message():
        while True:
            await asyncio.sleep(10.0)
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
            await channel_acceptor.accept_channels()
        except asyncio.CancelledError:
            logger.debug('channel_acceptor shutting down')

    async def service_grpc(self):
        server = grpc.aio.server()
        manager_grpc.add_MangagerServicer_to_server(
            ManagerBackend(self), server)
        server.add_insecure_port('[::]:50051')
        await server.start()
        logger.info("Rpc server started.")
        await server.wait_for_termination()

    async def run_services(self):
        """Main method to start registered services."""
        loop = asyncio.get_event_loop()
        if ASYNCIO_DEBUG:
            loop.set_debug(True)
            loop.slow_callback_duration = 0.01
            warnings.simplefilter('always', ResourceWarning)

        # register signal handler for process cancelation
        for sig in (SIGTERM, SIGINT):
            loop.add_signal_handler(sig, handler, sig)

        self.running_services = {
            'grpc': self.service_grpc(),
            'channel_acceptor': self.service_channel_acceptor(),
            'alive_message': self.service_alive_message(),
            # 'htlc_stream': self.service_htlc_stream(),
            # 'graph_stream': self.service_graph_stream(),
        }

        # run services
        try:
            async with self.node:
                await asyncio.gather(*self.running_services.values())
        except asyncio.CancelledError:
            logger.debug('main shutting down')
        except Exception as e:
            logger.exception("exception occured")


class ManagerBackend(manager_grpc.MangagerServicer):
    def __init__(self, managed: LNDManageDaemon):
        self.managed = managed

    def RunningServices(
            self,
            request: manager.RunningServicesRequest,
            context,
    ) -> manager.RunningServicesResponse:

        service_names = []

        for name, service in self.managed.running_services.items():
            service_names.append(manager.RunningService(name=name))

        return manager.RunningServicesResponse(services=service_names)

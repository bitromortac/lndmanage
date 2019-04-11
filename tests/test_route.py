from unittest import TestCase

from lib.routing import Route, Router
from lib.node import LndNode
import _settings

import logging.config

logging.config.dictConfig(_settings.logger_config)

# TODO: design networkx test graph


class TestRouter(TestCase):
    def setUp(self):
        self.node = LndNode()
        self.router = Router(self.node)

    def test_get_routes_along_nodes(self):
        node_from = '000000000000000000000000000000000000000000000000000000000000000000'
        node_to = '000000000000000000000000000000000000000000000000000000000000000000'
        amt = 100
        routes = self.router.get_routes_along_nodes(node_from, node_to, amt, number_of_routes=2)
        print(routes)

    def test_route(self):
        """
        to test a route, run
        $ lncli queryroutes source amt
        and copy-paste channel ids here and compare the results
        """

        route = Route(self.node, [000000000000000000, 000000000000000000],
                      '000000000000000000000000000000000000000000000000000000000000000000', 333000)
        route.debug_route()
        print('\nFinal route with reverse chain of fees:')
        print(self.node.lnd_route(route))

    def test_node_route_to_channel_route(self):
        hops = self.router.node_route_to_channel_route(
            ['000000000000000000000000000000000000000000000000000000000000000000',
             '000000000000000000000000000000000000000000000000000000000000000000',
             '000000000000000000000000000000000000000000000000000000000000000000', ],
            amt_msat=100)
        print(hops)

    def test_get_routes_for_advanced_rebalancing(self):
        self.router.get_routes_for_advanced_rebalancing(
            000000000000000000, 000000000000000000, 100, number_of_routes=10)

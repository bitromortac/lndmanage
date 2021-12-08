"""
Integration tests for batch opening of channels.
"""
from typing import Dict
from unittest import TestCase, mock

from lndmanage.lib.network import Network
from lndmanage.lib.rating import ChannelRater
from lndmanage.lib.pathfinding import dijkstra

from graph_definitions.routing_graph import nodes as test_graph


def new_test_graph(graph: Dict):
    # we need to init the node interface with a public key
    class MockNode:
        pub_key = 'A'

    # we disable cached graph reading
    with mock.patch.object(Network, 'cached_reading_graph_edges', return_value=None):
        network = Network(MockNode())

    # add nodes
    for node, node_definition in graph.items():
        network.graph.add_node(
            node,
            alias=node,
            last_update=None,
            address=None,
            color=None)

    # add channels
    for node, node_definition in graph.items():
        for channel, channel_definition in node_definition['channels'].items():
            # create a dictionary for channel_id lookups
            to_node = channel_definition['to']
            network.edges[channel] = {
                'node1_pub': node,
                'node2_pub': to_node,
                'capacity': channel_definition['capacity'],
                'last_update': None,
                'channel_id': channel,
                'chan_point': channel,
                'policies': {
                    node > to_node: channel_definition['policies'][node > to_node],
                    to_node > node: channel_definition['policies'][to_node > node],
                }
            }

            # add vertices to network graph for edge-based lookups
            network.graph.add_edge(
                node,
                to_node,
                channel_id=channel,
                last_update=None,
                capacity=channel_definition['capacity'],
                fees={
                    node > to_node: channel_definition['policies'][node > to_node],
                    to_node > node: channel_definition['policies'][to_node > node],
                })

    return network


class TestGraph(TestCase):
    def test_network(self):
        n = new_test_graph(test_graph)
        self.assertEqual(5, n.graph.number_of_nodes())
        self.assertEqual(7, n.graph.number_of_edges())

    def test_shortest_path(self):
        network = new_test_graph(test_graph)
        cr = ChannelRater(network)
        amt_msat = 1_000_000
        weight_function = lambda v, u, e: cr.node_to_node_weight(v, u, e, amt_msat)
        print(dijkstra(network.graph, 'A', 'E', weight=weight_function))
        # TODO: use too high capacity
        # TODO: use parallel channels with different policies

    def test_liquidity_hints(self):
        """
                3
            A  ---  B
            |    2/ |
          6 |   E   | 1
            | /5 \7 |
            D  ---  C
                4
        """
        amt_msat = 100_000 * 1_000
        network = new_test_graph(test_graph)
        cr = ChannelRater(network=network)
        weight_function = lambda v, u, e: cr.node_to_node_weight(v, u, e, amt_msat)

        path = dijkstra(network.graph, 'A', 'E', weight=weight_function)
        self.assertEqual(['A', 'B', 'E'], path)

        # We report that B cannot send to E
        network.liquidity_hints.update_cannot_send('B', 'E', 2, 1_000)
        path = dijkstra(network.graph, 'A', 'E', weight=weight_function)
        self.assertEqual(['A', 'D', 'E'], path)

        # We report that D cannot send to E
        network.liquidity_hints.update_cannot_send('D', 'E', 5, 1_000)
        path = dijkstra(network.graph, 'A', 'E', weight=weight_function)
        self.assertEqual(['A', 'B', 'C', 'E'], path)

        # We report that D can send to C
        network.liquidity_hints.update_can_send('D', 'C', 4, amt_msat + 1000)
        path = dijkstra(network.graph, 'A', 'E', weight=weight_function)
        self.assertEqual(['A', 'D', 'C', 'E'], path)

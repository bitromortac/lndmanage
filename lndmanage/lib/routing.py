from typing import List, Dict, TYPE_CHECKING, Tuple

from lndmanage.lib.exceptions import RouteWithTooSmallCapacity, NoRoute
from lndmanage.lib.pathfinding import dijkstra
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def calculate_fees_on_policy(amt_msat, policy):
    return policy['fee_base_msat'] + amt_msat * policy['fee_rate_milli_msat'] // 1000000


class Route(object):
    """Deals with the onion route construction from list of channels. Calculates fees
    and cltvs.
    """

    def __init__(self, node: 'LndNode', channel_hops: List[int], node_dest: str, amt_msat: int):
        """
        :param node: :class:`lib.node.Node` instance
        :param channel_hops: list of chan_ids along which the route shall be constructed
        :param node_dest: pub_key of destination node
        :param amt_msat: amount to send in msat
        """

        self.node = node
        self.blockheight = node.blockheight
        logger.debug(f"Blockheight: {self.blockheight}")
        self.channel_hops = channel_hops
        self._hops = []
        self._node_hops = [node_dest]
        forward_msat = amt_msat
        final_cltv = 144
        fees_msat_container = [0]
        cltv_delta = [0]
        node_right = node_dest
        node_left = None
        policy = None

        logger.debug("Route construction starting.")
        # hops are traversed in backwards direction to accumulate fees and cltvs
        for ichannel, channel_id in enumerate(reversed(channel_hops)):
            channel_data = self.node.network.edges[channel_id]
            # TODO: add private channels for sending

            if amt_msat // 1000 > channel_data['capacity']:
                logger.debug(f"Discovered a channel {channel_id} with too small capacity.")
                raise RouteWithTooSmallCapacity(f"Amount too large for channel.")

            policies = channel_data['policies']
            if node_right == channel_data['node2_pub']:
                try:
                    policy = policies[channel_data['node1_pub'] > channel_data['node2_pub']]
                    node_left = channel_data['node1_pub']
                except KeyError:
                    logger.exception(f"No channel {channel_data}")
            else:
                policy = policies[channel_data['node2_pub'] > channel_data['node1_pub']]
                node_left = channel_data['node2_pub']

            self._node_hops.append(node_left)
            hop = len(channel_hops) - ichannel
            logger.info(f"    Hop {hop}: {channel_id} (cap: {channel_data['capacity']} sat): "
                        f"{self.node.network.node_alias(node_right)} <- {self.node.network.node_alias(node_left)} ")
            logger.debug(f"      Policy of forwarding node: {policy}")

            fees_msat = policy['fee_base_msat'] + policy['fee_rate_milli_msat'] * forward_msat // 1000000
            forward_msat = amt_msat + sum(fees_msat_container[:ichannel])
            fees_msat_container.append(fees_msat)

            logger.info(f"      Fees: {fees_msat / 1000 if not hop == 1 else 0:3.3f} sat")
            logger.debug(f"      Fees container {fees_msat_container}")
            logger.debug(f"      Forward: {forward_msat / 1000:3.3f} sat")
            logger.info(f"      Liquidity penalty: {self.node.network.liquidity_hints.penalty(node_left, node_right, channel_data, amt_msat, self.node.network.channel_rater.reference_fee_rate_milli_msat) / 1000: 3.3f} sat")

            self._hops.append({
                'chan_id': channel_data['channel_id'],
                'chan_capacity': channel_data['capacity'],
                'amt_to_forward': forward_msat // 1000,
                'fee': fees_msat_container[-2] // 1000,
                'expiry': self.blockheight + final_cltv + sum(cltv_delta[:ichannel]),
                'amt_to_forward_msat': forward_msat,
                'fee_msat': fees_msat_container[-2],
            })

            cltv_delta.append(policy['time_lock_delta'])
            node_right = node_left

        self.hops = list(reversed(self._hops))
        self.node_hops = list(reversed(self._node_hops))
        self.total_amt_msat = amt_msat + sum(fees_msat_container[:-1])
        self.total_fee_msat = sum(fees_msat_container[:-1])
        self.total_time_lock = sum(cltv_delta[:-1]) + self.blockheight + final_cltv

    def _debug_route(self):
        """Prints detailed information of the route."""
        logger.debug("Debug route:")
        for h in self.hops:
            logger.debug(f"c:{h['chan_id']} a:{h['amt_to_forward']} f:{h['fee_msat']}"
                         f" c:{h['expiry'] - self.node.blockheight}")
            channel_info = self.node.network.edges[h['chan_id']]
            node1 = channel_info['node1_pub']
            node2 = channel_info['node2_pub']
            logger.debug(f"{node1[:5]}, {channel_info['node1_policy']}")
            logger.debug(f"{node2[:5]}, {channel_info['node2_policy']}")
        logger.debug(f"tl:{self.total_time_lock} ta:{self.total_amt_msat} tf:{self.total_fee_msat}")


class Router(object):
    """Contains utilities for constructing routes."""

    def __init__(self, node: 'LndNode'):
        self.node = node

    def _node_route_to_channel_route(self, node_route: List[str], amt_msat: int) -> List[int]:
        """Takes a route in terms of a list of nodes and translates it into a list of
        channels.

        :param node_route: list of pubkeys
        :param amt_msat: amount to send in sat
        :return: list of channel_ids
        """
        channels = []
        for p in range(len(node_route) - 1):
            channels.append(
                self._determine_channel(
                    node_route[p], node_route[p + 1], amt_msat)[1])
        return channels

    def get_route_from_to_nodes(self, node_from: str, node_to: str, amt_msat: int) -> List[str]:
        """Determines number_of_routes shortest paths between node_from and node_to for
        an amount of amt_msat.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msat
        :return: route
        """
        self.node.network.channel_rater.blacklisted_nodes.append(self.node.pub_key)  # excludes self-loops

        weight_function = lambda v, u, e: self.node.network.channel_rater.node_to_node_weight(v, u, e, amt_msat)
        route = dijkstra(self.node.network.graph, node_from, node_to, weight=weight_function)

        if not route:
            raise NoRoute

        return route

    def _determine_channel(self, node_from: str, node_to: str, amt_msat: int):
        """Determines the cheapest channel between nodes node_from and node_to for an
        amount of amt_msat.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msat
        :return: channel_id
        """
        number_edges = self.node.network.graph.number_of_edges(node_from, node_to)
        channels_with_calculated_fees = []
        for n in range(number_edges):
            edge = self.node.network.graph.get_edge_data(node_from, node_to, n)
            fees = self.node.network.channel_rater.channel_weight(node_from, node_to, edge, amt_msat)
            channels_with_calculated_fees.append([fees, edge['channel_id']])
        sorted_channels = sorted(channels_with_calculated_fees, key=lambda k: k[0])
        best_channel = sorted_channels[0]
        # we check that we don't encounter a hop which is blacklisted
        if best_channel[0] == float('inf'):
            raise NoRoute('channels graph exhausted')
        return best_channel

    def _determine_cheapest_fees_between_two_nodes(self, node_from, node_to, amt_msat):
        return self._determine_channel(node_from, node_to, amt_msat)[0]

    def get_route_channel_hops_from_to_node_internal(
            self,
            source_pubkey: str,
            target_pubkey: str,
            amt_msat: int
    ) -> List[int]:
        """Find routes internally, using networkx to construct a route from a source
        node to a target node."""
        logger.debug(f"Internal pathfinding:")
        logger.debug(f"from {source_pubkey}")
        logger.debug(f"  to {target_pubkey}")

        node_route = self.get_route_from_to_nodes(
            source_pubkey, target_pubkey, amt_msat)

        return self._node_route_to_channel_route(node_route, amt_msat)

    def get_route(
            self,
            send_channels: Dict[int, dict],
            receive_channels: Dict[int, dict],
            amt_msat: int
    ) -> Route:
        """Calculates a route from send_channels to receive_channels.

        :param send_channels: channel ids to send from
        :param receive_channels: channel ids to receive to
        :param amt_msat: payment amount in msat

        :return: a route for rebalancing
        """
        this_node = self.node.pub_key # TODO: make this a parameter for general route calculation
        self.node.network.channel_rater.reset_channel_blacklist()

        # We will ask for a route from source to target.
        # we send via a send channel and receive over other channels:
        # this_node -(send channel)-> source -> ... -> receiver neighbors -(receive channels)-> target (this_node)
        if len(send_channels) == 1:
            send_channel = list(send_channels.values())[0]
            source = send_channel['remote_pubkey']
            target = this_node

            # we don't want to go backwards via the send_channel (and other parallel channels)
            channels_source_target = self.node.network.graph[source][target]
            for channel in channels_source_target.values():
                self.node.network.channel_rater.blacklist_add_channel(channel['channel_id'], source, target)

            # we want to use the receive channels for receiving only, so don't receive over other channels
            excluded_receive_channels = self.node.get_unbalanced_channels(
                excluded_channels=[k for k in receive_channels.keys()], public_only=False, active_only=False)
            for channel_id, channel in excluded_receive_channels.items():
                receiver_neighbor = channel['remote_pubkey']
                self.node.network.channel_rater.blacklist_add_channel(channel_id, receiver_neighbor, target)

        # we send via several channels and receive over a single one:
        # this_node (source) -(send channels)-> ... -> receiver neighbor (target) -(receive channel)-> this_node
        elif len(receive_channels) == 1:
            receive_channel = list(receive_channels.values())[0]
            source = this_node
            target = receive_channel['remote_pubkey']

            # we want to block the receiving channel (and parallel ones) from sending
            channels_source_target = self.node.network.graph[source][target]
            for channel in channels_source_target.values():
                self.node.network.channel_rater.blacklist_add_channel(channel['channel_id'], source, target)

            # we want to use the send channels for sending only, so don't send over other channels
            excluded_send_channels = self.node.get_unbalanced_channels(
                excluded_channels=[k for k in send_channels.keys()], public_only=False, active_only=False)
            for channel_id, channel in excluded_send_channels.items():
                sender_neighbor = channel['remote_pubkey']
                self.node.network.channel_rater.blacklist_add_channel(channel_id, source, sender_neighbor)
        else:
            raise ValueError("One of the two channel sets should be singular.")

        # determine inner channel hops
        # internal method uses networkx dijkstra,
        # this is more independent, but slower
        route_channel_hops = \
            self.get_route_channel_hops_from_to_node_internal(
            source, target, amt_msat)

        final_channel_hops = []
        if len(send_channels) == 1:
            final_channel_hops.append(send_channel['chan_id'])
            final_channel_hops.extend(route_channel_hops)
        else:
            final_channel_hops.extend(route_channel_hops)
            final_channel_hops.append(receive_channel['chan_id'])

        # TODO: add some consistency checks, route shouldn't contain self-loops
        logger.debug("Channel hops:")
        logger.debug(final_channel_hops)

        # initialize Route objects with appropriate fees and expiries
        route = Route(self.node, final_channel_hops, this_node, amt_msat)

        return route


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(settings.logger_config)
    from lndmanage.lib.node import LndNode
    nd = LndNode()

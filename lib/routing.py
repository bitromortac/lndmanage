import _settings

from lib.pathfinding import ksp_discard_high_cost_paths
from lib.exceptions import RouteWithTooSmallCapacity
from lib.rating import ChannelRater

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def calculate_fees_on_policy(amt_msat, policy):
    return policy['fee_base_msat'] + amt_msat * policy['fee_rate_milli_msat'] // 1000000


class Route(object):
    """
    Deals with the onion route construction from list of channels. Calculates fees and cltvs.

    :param node: :class:`lib.node.Node` instance
    :param channel_hops: list of chan_ids along which the route shall be constructed
    :param node_dest: pub_key of destination node
    :param amt_msat: amount to send in msats
    """

    def __init__(self, node, channel_hops, node_dest, amt_msat):
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

            if amt_msat // 1000 > channel_data['capacity']:
                logger.debug(f"Discovered a channel {channel_id} with too small capacity.")
                raise RouteWithTooSmallCapacity(f"Amount too large for channel.")

            if node_right == channel_data['node2_pub']:
                try:
                    policy = channel_data['node1_policy']
                    node_left = channel_data['node1_pub']
                except KeyError:
                    logger.exception(f"No channel {channel_data}")
            else:
                policy = channel_data['node2_policy']
                node_left = channel_data['node2_pub']

            self._node_hops.append(node_left)

            logger.debug(f"From {node_left} to {node_right}")
            logger.debug(f"Policy of forwarding node: {policy}")

            fees_msat = policy['fee_base_msat'] + policy['fee_rate_milli_msat'] * forward_msat // 1000000
            forward_msat = amt_msat + sum(fees_msat_container[:ichannel])
            fees_msat_container.append(fees_msat)

            logger.debug(f"Hop: {len(channel_hops) - ichannel}")
            logger.debug(f"     Fees: {fees_msat}")
            logger.debug(f"     Fees container {fees_msat_container}")
            logger.debug(f"     Forward: {forward_msat}")

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

    def debug_route(self):
        """
        Prints detailed information of the route.
        """
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
    """
    Contains utilities for constructing routes.

    :param node: :class:`lib.node.Node` instance
    """

    def __init__(self, node):
        self.node = node
        self.channel_rater = ChannelRater()

    def node_route_to_channel_route(self, node_route, amt_msat):
        """
        Takes a route in terms of a list of nodes and translates it into a list of channels.

        :param node_route: list of pubkeys
        :param amt_msat: amount to send in sats
        :return: list of channel_ids
        """
        # TODO refactor this with channel_rater
        channels = []
        for p in range(len(node_route) - 1):
            # TODO: refactor, code is ugly
            channels.append(
                self.determine_cheapest_channel_between_two_nodes(
                    node_route[p], node_route[p + 1], amt_msat)[1])
        return channels

    def get_routes_along_nodes(self, node_from, node_to, amt_msat, number_of_routes=10):
        """
        Determines number_of_routes shortest paths between node_from and node_to for an amount of amt_msat.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msats
        :param number_of_routes: int
        :return: number_of_routes lists of node pubkeys
        """
        self.channel_rater.bad_nodes.append(self.node.pub_key)  # excludes self-loops

        weight_function = lambda v, u, e: self.channel_rater.node_to_node_weight(v, u, e, amt_msat)
        routes = ksp_discard_high_cost_paths(
            self.node.network.graph, node_from, node_to,
            num_k=number_of_routes, weight=weight_function)
        return routes

    def determine_cheapest_channel_between_two_nodes(self, node_from, node_to, amt_msat):
        """
        Determines the cheapest channel between nodes node_from and node_to for an amount of amt_msat.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msats
        :return: channel_id
        """
        # TODO refactor with channel_rater

        number_edges = self.node.network.graph.number_of_edges(node_from, node_to)
        channels_with_calculated_fees = []
        for n in range(number_edges):
            edge = self.node.network.graph.get_edge_data(node_from, node_to, n)
            fees = self.channel_rater.channel_weight(edge, amt_msat)
            channels_with_calculated_fees.append([fees, edge['channel_id']])
        sorted_channels = sorted(channels_with_calculated_fees, key=lambda k: k[0])
        return sorted_channels[0]

    def determine_cheapest_fees_between_two_nodes(self, node_from, node_to, amt):
        return self.determine_cheapest_channel_between_two_nodes(node_from, node_to, amt)[0]

    def get_routes_for_advanced_rebalancing(self, chan_id_from, chan_id_to, amt_msat, number_of_routes):
        """
        Calculates a path for channel_id_from to chan_id_to and optimizes for fees for an amount amt.

        :param chan_id_from:
        :param chan_id_to:
        :param amt_msat:
        :param number_of_routes:
        :return: list of :class:`lib.routing.Route` instances
        """

        channel_from = self.node.network.edges[chan_id_from]
        channel_to = self.node.network.edges[chan_id_to]
        this_node = self.node.pub_key

        # determine nodes on the other side, between which we need to find a suitable path between
        # TODO: think about logic
        if channel_from['node1_pub'] == this_node:
            node_from = channel_from['node2_pub']
        else:
            node_from = channel_from['node1_pub']

        if channel_to['node1_pub'] == this_node:
            node_to = channel_to['node2_pub']
        else:
            node_to = channel_to['node1_pub']

        logger.debug(f"Finding routes from {node_from} to {node_to}.")
        # find path between the two nodes
        node_routes = self.get_routes_along_nodes(
            node_from, node_to, amt_msat, number_of_routes=number_of_routes)
        logger.debug("Intermediate nodes:")
        for r in node_routes:
            logger.debug(r)

        # initialize Route objects with appropriate fees and expiries
        routes = []
        for r in node_routes:
            hops = self.node_route_to_channel_route(r, amt_msat)
            # add our channels to the hops
            hops.insert(0, chan_id_from)
            hops.append(chan_id_to)
            logger.debug("Channel hops:")
            logger.debug(hops)
            try:
                route = Route(self.node, hops, this_node, amt_msat)
                routes.append(route)
            except RouteWithTooSmallCapacity:
                continue
        return routes


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(_settings.logger_config)
    from lib.node import LndNode
    nd = LndNode()

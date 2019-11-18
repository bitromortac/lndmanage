from lndmanage.lib.rating import ChannelRater
from lndmanage.lib.exceptions import RouteWithTooSmallCapacity, NoRoute
from lndmanage.lib.pathfinding import ksp_discard_high_cost_paths
from lndmanage import settings

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
    :param amt_msat: amount to send in msat
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

            logger.debug(f"Route from {node_left}")
            logger.debug(f"        to {node_right}")
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

    def _debug_route(self):
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

    def _node_route_to_channel_route(self, node_route, amt_msat):
        """
        Takes a route in terms of a list of nodes and translates it into a list of channels.

        :param node_route: list of pubkeys
        :param amt_msat: amount to send in sat
        :return: list of channel_ids
        """
        channels = []
        for p in range(len(node_route) - 1):
            channels.append(
                self._determine_cheapest_channel_between_two_nodes(
                    node_route[p], node_route[p + 1], amt_msat)[1])
        return channels

    def get_routes_from_to_nodes(self, node_from, node_to, amt_msat, number_of_routes=10):
        """
        Determines number_of_routes shortest paths between node_from and node_to for an amount of amt_msat.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msat
        :param number_of_routes: int
        :return: number_of_routes lists of node pubkeys
        """
        self.channel_rater.bad_nodes.append(self.node.pub_key)  # excludes self-loops

        weight_function = lambda v, u, e: self.channel_rater.node_to_node_weight(v, u, e, amt_msat)
        routes = ksp_discard_high_cost_paths(
            self.node.network.graph, node_from, node_to,
            num_k=number_of_routes, weight=weight_function)

        if not routes:
            raise NoRoute

        return routes

    def _determine_cheapest_channel_between_two_nodes(self, node_from, node_to, amt_msat):
        """
        Determines the cheapest channel between nodes node_from and node_to for an amount of amt_msat.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msat
        :return: channel_id
        """
        number_edges = self.node.network.graph.number_of_edges(node_from, node_to)
        channels_with_calculated_fees = []
        for n in range(number_edges):
            edge = self.node.network.graph.get_edge_data(node_from, node_to, n)
            fees = self.channel_rater.channel_weight(edge, amt_msat)
            channels_with_calculated_fees.append([fees, edge['channel_id']])
        sorted_channels = sorted(channels_with_calculated_fees, key=lambda k: k[0])
        return sorted_channels[0]

    def _determine_cheapest_fees_between_two_nodes(self, node_from, node_to, amt):
        return self._determine_cheapest_channel_between_two_nodes(node_from, node_to, amt)[0]

    def get_route_channel_hops_from_to_node_internal(self, source_pubkey, target_pubkey, amt_msat):
        """
        Find routes internally, using networkx to construct a route from a source node to a target node.

        :param source_pubkey: str
        :param target_pubkey: str
        :param amt_msat: int
        :return:
        """
        logger.debug(f"Internal route finding:")
        logger.debug(f"from {source_pubkey}")
        logger.debug(f"  to {target_pubkey}")

        node_routes = self.get_routes_from_to_nodes(
            source_pubkey, target_pubkey, amt_msat, number_of_routes=1)

        hops = self._node_route_to_channel_route(node_routes[0], amt_msat)

        # logger.debug(f"(Intermediate) route as channel hops: {hops}")
        return [hops]

    def get_route_channel_hops_from_to_node_external(
            self, source_pubkey, target_pubkey, amt_msat, use_mc=False):
        """
        Find routes externally (relying on the node api) to construct a route
        from a source node to a target node.

        :param source_pubkey: source public key
        :type source_pubkey: str
        :param target_pubkey: target public key
        :type target_pubkey: str
        :param amt_msat: amount to send in msat
        :type amt_msat: int
        :param use_mc: true if mission control based pathfinding is used
        :type use_mc: bool
        :return: list of hops
        :rtype: list[list[int]]
        """
        logger.debug(f"External pathfinding, using mission control: {use_mc}.")
        logger.debug(f"from {source_pubkey}")
        logger.debug(f"  to {target_pubkey}")
        ignored_nodes = self.channel_rater.bad_nodes

        # we don't need to give blacklisted channels to the queryroute command
        # as all of this is done by mission control
        if use_mc:
            ignored_channels = {}
        else:
            ignored_channels = self.channel_rater.bad_channels

        hops = self.node.queryroute_external(
            source_pubkey, target_pubkey, amt_msat,
            ignored_channels=ignored_channels,
            ignored_nodes=ignored_nodes,
            use_mc=use_mc,
        )

        return [hops]

    def get_routes_for_rebalancing(
            self, chan_id_from, chan_id_to, amt_msat, method='external'):
        """
        Calculates several routes for channel_id_from to chan_id_to
        and optimizes for fees for an amount amt.

        :param chan_id_from: short channel id of the from node
        :type chan_id_from: int
        :param chan_id_to: short channel id of the to node
        :type chan_id_to: int
        :param amt_msat: payment amount in msat
        :type amt_msat: int
        :param method: specifies if 'internal', or 'external'
               method of route computation should be used
        :type method: string
        :return: list of :class:`lib.routing.Route` instances
        :rtype: list[lndmanage.lib.routing.Route]
        """

        try:
            channel_from = self.node.network.edges[chan_id_from]
            channel_to = self.node.network.edges[chan_id_to]
        except KeyError:
            logger.exception(
                "Channel was not found in network graph, but is present in "
                "listchannels. Channel needs 6 confirmations to be usable.")
            raise NoRoute

        this_node = self.node.pub_key

        # find the correct node_pubkeys between which we want to route
        # fist hop:start-end ----- last hop: start-end
        if channel_from['node1_pub'] == this_node:
            first_hop_end = channel_from['node2_pub']
        else:
            first_hop_end = channel_from['node1_pub']

        if channel_to['node1_pub'] == this_node:
            last_hop_start = channel_to['node2_pub']
        else:
            last_hop_start = channel_to['node1_pub']

        # determine inner channel hops
        # internal method uses networkx dijkstra,
        # this is more independent, but slower
        if method == 'internal':
            routes_channel_hops = \
                self.get_route_channel_hops_from_to_node_internal(
                first_hop_end, last_hop_start, amt_msat)
        # rely on external pathfinding with internal blacklisting
        elif method == 'external':
            routes_channel_hops = \
                self.get_route_channel_hops_from_to_node_external(
                first_hop_end, last_hop_start, amt_msat, use_mc=False)
        # rely on external pathfinding using mission control
        elif method == 'external-mc':
            routes_channel_hops = \
                self.get_route_channel_hops_from_to_node_external(
                first_hop_end, last_hop_start, amt_msat, use_mc=True)
        else:
            raise ValueError(
                f"Method must be either internal, external or external-mc, "
                f"is {method}.")

        # pre- and append the outgoing and incoming channels to the route
        routes_channel_hops_final = []
        for r in routes_channel_hops:
            r.insert(0, chan_id_from)
            r.append(chan_id_to)
            logger.debug("Channel hops:")
            logger.debug(r)
            routes_channel_hops_final.append(r)

        # initialize Route objects with appropriate fees and expiries
        routes = []
        for h in routes_channel_hops:
            try:
                route = Route(self.node, h, this_node, amt_msat)
                routes.append(route)
            except RouteWithTooSmallCapacity:
                continue
        return routes


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(settings.logger_config)
    from lndmanage.lib.node import LndNode
    nd = LndNode()

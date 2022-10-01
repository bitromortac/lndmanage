from typing import List, Dict, TYPE_CHECKING
import random

import grpc

from lndmanage.lib.data_types import NodePair
from lndmanage.lib.exceptions import NoRoute
from lndmanage.lib.pathfinding import dijkstra
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode
    import lndmanage.grpc_compiled.lightning_pb2 as lnd

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

def fees_for_policy(amt_msat, policy):
    return policy['fee_base_msat'] + \
        amt_msat * policy['fee_rate_milli_msat'] // 1000000


class Router(object):
    """Contains utilities for route construction."""

    def __init__(self, node: 'LndNode'):
        self.node = node

    def find_path(self, node_from: str, node_to: str,
                  amt_msat: int) -> List[str]:
        """Looks for a path from one node to another for a certain amount.

        :param node_from: pubkey
        :param node_to: pubkey
        :param amt_msat: amount to send in msat

        :return: list of pubkey hops
        """

        # Exclude self-loops.
        self.node.network.channel_rater.blacklisted_nodes.append(
            self.node.pub_key,
        )

        def weight_function(v, u, e):
            return self.node.network.channel_rater.node_to_node_weight(
                v, u, e, amt_msat,
            )

        # Perform a Dijkstra shortest path search.
        # TODO: known limitation: does not include fees of fees.
        route = dijkstra(
            self.node.network.graph, node_from, node_to, weight=weight_function,
        )

        return route

    def check_route(self, route):
        """Checks a route for sanity and gives debug output."""

        # We check that the route is not just sending and receiveing over the
        # same channel.
        if len(route.hops) == 2:
            raise NoRoute(f"only minimal route available: self -> other -> "+
                              "self: {rpc_error.details()}")

        # We check that the chosen channels have some finite chance of success
        # and that they are not blacklisted.
        node_from = self.node.pub_key
        for i, hop in enumerate(route.hops):
            node_to = hop.pub_key

            # We don't want our node to be inside the path.
            if i > 0 and i < len(route.hops) - 1:
                assert node_to != self.node.pub_key, "our node is inside of the path"

            # Fetch the channel policy.
            edge_data = None
            edges = self.node.network.graph[node_from][node_to]
            for edge in edges.values():
                if edge['channel_id'] == hop.chan_id:
                    edge_data = edge
                    break
            if not edge_data:
                raise NoRoute("channel not found in local graph")

            # Display some debug output.
            logger.info(f"    Hop {i}: {hop.chan_id} (cap: {edge_data['capacity']} sat): "
                        f"{self.node.network.node_alias(node_from)} -> " +
                        f"{self.node.network.node_alias(node_to)}")
            logger.debug(f"      Fees next: {hop.fee_msat:9.3f} sat")

            _ = self.node.network.channel_rater.channel_weight(
                node_from, node_to, edge_data, hop.amt_to_forward_msat,
            )

            node_from = node_to

    def find_node_route(self, source_pubkey: str, target_pubkey: str,
                 amt_msat: int) -> List[int]:
        """Finds a route from source to target for a certain amount. Returns a
        list of pubkeys."""

        logger.debug(f"Internal pathfinding:")
        logger.debug(f"from {source_pubkey}")
        logger.debug(f"  to {target_pubkey}")

        node_hops = self.find_path(
            source_pubkey, target_pubkey, amt_msat)

        return node_hops

    def route_from_constraints(
            self,
            send_channels: Dict[int, dict],
            receive_channels: Dict[int, dict],
            amt_msat: int,
            payment_addr: bytes,
    ) -> 'lnd.Route':
        """Calculates a route that leaves over send_channels and enters via
        receive_channels.

        :param send_channels: channel ids to send from
        :param receive_channels: channel ids to receive to
        :param amt_msat: payment amount in msat

        :return: a route that can be sent do via the lnd api
        """

        this_node = self.node.pub_key

        # Reset old blacklists.
        self.node.network.channel_rater.reset_channel_blacklist()

        # We will ask for a route from source to target. The specific source and
        # target depends on the input channels.

        # Case1: single send channel and multiple receive channels:
        #   * this_node -(send channel)->
        #   [* source ->
        #   ... ->
        #   * receiver neighbors -(receive channels)->
        #   * target (this_node)]
        #   Look for a path in parantheses.

        if len(send_channels) == 1:
            # There is only a single send channel.
            send_channel = list(send_channels.values())[0]

            source = send_channel['remote_pubkey']
            target = this_node

            # We don't want to go backwards via the send_channel and other
            # parallel channels between source and target.
            blocked_channels = self.node.network.graph[source][target]
            for channel in blocked_channels.values():
                self.node.network.channel_rater.blacklist_add_channel(
                    channel['channel_id'], source, target,
                )

            # We exclude all other channels other than receive channels from
            # receiving.

            excluded_receive_channels = self.node.get_unbalanced_channels(
                excluded_channels=[k for k in receive_channels.keys()],
                public_only=False, active_only=False,
            )

            for channel_id, channel in excluded_receive_channels.items():
                receiver_neighbor = channel['remote_pubkey']
                self.node.network.channel_rater.blacklist_add_channel(
                    channel_id, receiver_neighbor, target,
                )

        # Case 2: send via several channels and receive over a single one
        # * [this_node (source) -(send channels)->
        # * ... ->
        # * receiver neighbor (target)] -(receive channel)->
        # * this_node
        elif len(receive_channels) == 1:
            # We have only a single receive channel.
            receive_channel = list(receive_channels.values())[0]

            source = this_node
            target = receive_channel['remote_pubkey']

            # We want to block the receiving channel and parallel ones from
            # sending.
            blocked_channels = self.node.network.graph[source][target]
            for channel in blocked_channels.values():
                self.node.network.channel_rater.blacklist_add_channel(
                    channel['channel_id'], source, target,
                )

            # We want to use the send channels for sending only, so don't send
            # over other channels.
            excluded_send_channels = self.node.get_unbalanced_channels(
                excluded_channels=[k for k in send_channels.keys()],
                public_only=False, active_only=False)

            for channel_id, channel in excluded_send_channels.items():
                sender_neighbor = channel['remote_pubkey']
                self.node.network.channel_rater.blacklist_add_channel(
                    channel_id, source, sender_neighbor,
                )
        else:
            raise ValueError("One of the two channel sets should be singular.")

        # Up to this point, we have determined source and target channels.

        # Compute hops from source to target.
        hop_pubkeys = self.find_node_route(
            source, target, amt_msat,
        )

        # Construct the final list of nodes.
        final_hop_pubkeys = []
        outgoing_channel = None

        # Single-send channel, multiple receive channels.
        if len(send_channels) == 1:
            final_hop_pubkeys.extend(hop_pubkeys)
            outgoing_channel = send_channel['chan_id']

        # Multiple send channels, single receive channel.
        else:
            # We need to extend the path with the pubkey of this node.
            final_hop_pubkeys.extend(hop_pubkeys[1:])
            final_hop_pubkeys.append(this_node)

            # For the outgoing channel, select a channel from the send channels
            # with the nearest neighbor (second pubkey).
            send_candidates = [c for c, v in send_channels.items() if
                v['remote_pubkey'] == final_hop_pubkeys[0]]

            # TODO: select a better send channel if multiple are available.
            outgoing_channel = random.choice(send_candidates)

        logger.debug("Node hops:")
        logger.debug(final_hop_pubkeys)

        logger.info(f"Construct route for {len(final_hop_pubkeys)} hops.")

        # Build a route via an RPC call to LND.
        try:
            route = self.node.build_route(
                amt_msat, outgoing_channel, final_hop_pubkeys, payment_addr,
            )
        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.UNKNOWN:
                if "for node 0" in rpc_error.details():
                    raise NoRoute(f"our node can't send: {rpc_error.details()}")
                raise NoRoute(
                    f"could not build a route {final_hop_pubkeys}"
                    f"outgoing {outgoing_channel}: {rpc_error.details()}"
                )
            else:
                raise rpc_error

        self.check_route(route)

        return route


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(settings.logger_config)
    from lndmanage.lib.node import LndNode
    nd = LndNode()

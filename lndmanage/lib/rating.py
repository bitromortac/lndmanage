import math
from typing import TYPE_CHECKING

from lndmanage import settings

import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

if TYPE_CHECKING:
    from lndmanage.lib.network import Network


class ChannelRater:
    """The purpose of this class is to hold information about the balancedness of
    channels. It also defines the cost function of a channel with the function
    :func:`ChannelRater.lightning_channel_weight`.
    """

    def __init__(self, network: "Network", source: str = None):
        self.blacklisted_channels = {}
        self.blacklisted_nodes = []
        self.source = source
        self.network = network
        self.reference_fee_rate_milli_msat = 10

    def node_to_node_weight(self, u, v, e, amt_msat):
        """Is used to assign a weight for a channel. It is calculated from the fee
        policy of that channel:
        base fee + proportional fee + path penalty + capacity penalty + blacklist penalty

        :param u: source node
        :param v: target node
        :param e: fee policy of the edges
        :param amt_msat: amount in msat
        :return: cost of the channel in msat
        """
        node_penalty = 0
        if u in self.blacklisted_nodes or v in self.blacklisted_nodes:
            node_penalty = settings.PENALTY

        costs = [
            node_penalty + self.channel_weight(u, v, edge_properties, amt_msat)
            for edge_properties in e.values()
        ]
        return min(costs)

    def channel_weight(self, u, v, e, amt_msat):
        # check if channel is blacklisted
        if self.blacklisted_channels.get(e["channel_id"]) == {"source": u, "target": v}:
            return math.inf
        # we don't send if the channel cannot carry the payment
        if amt_msat // 1000 > e["capacity"]:
            return math.inf
        # we don't send over channel if it is disabled
        policy = e.get("fees")[u > v]
        if policy["disabled"]:
            return math.inf
        # we don't pay fees if we own the channel and are sending over it
        if self.source and u == self.source:
            return 0
        # compute liquidity penalty
        liquidity_penalty = self.network.liquidity_hints.penalty(
            u, v, e, amt_msat, self.reference_fee_rate_milli_msat
        )
        # compute fees and add penalty
        fees = (
            policy["fee_base_msat"]
            + amt_msat
            * (
                abs(policy["fee_rate_milli_msat"] - self.reference_fee_rate_milli_msat)
                + self.reference_fee_rate_milli_msat
            )
            // 1_000_000
        )

        return liquidity_penalty + fees

    def blacklist_add_channel(self, channel: int, source: str, target: str):
        """Adds a channel to the blacklist dict.

        :param channel: channel_id
        :param source: pubkey
        :param target: pubkey
        """
        self.blacklisted_channels[channel] = {
            "source": source,
            "target": target,
        }

    def reset_channel_blacklist(self):
        self.blacklisted_channels = {}

    def blacklist_add_node(self, node_pub_key):
        """Adds a node public key to the blacklist.

        :param node_pub_key: str
        """
        self.blacklisted_nodes.append(node_pub_key)

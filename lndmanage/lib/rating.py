from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class ChannelRater(object):
    """
    The purpose of this class is to hold information about the balancedness of channels.
    It also defines the cost function of a channel
    with the function :func:`ChannelRater.lightning_channel_weight`.
    """

    def __init__(self):
        self.bad_channels = {}
        self.bad_nodes = []

    def node_to_node_weight(self, u, v, e, amt_msat):
        """
        Is used to assign a weight for a channel. It is calculated from the fee policy of that channel:
        base fee + proportional fee + path penalty + capacity penalty + blacklist penalty

        :param u: source node
        :param v: target node
        :param e: fee policy of the edges
        :param amt_msat: amount in msat
        :return: cost of the channel in msat
        """
        node_penalty = 0
        if u in self.bad_nodes or v in self.bad_nodes:
            node_penalty = settings.PENALTY

        costs = [node_penalty + self.channel_weight(eattr, amt_msat) for eattr in e.values()]
        return min(costs)

    def channel_weight(self, e, amt_msat):
        long_path_penalty = 0
        if settings.PREFER_SHORT_PATHS:
            long_path_penalty = settings.LONG_PATH_PENALTY_MSAT

        cost = (long_path_penalty
                + e.get('fees')['fee_base_msat']
                + amt_msat * e.get('fees')['fee_rate_milli_msat'] // 1000000
                + self.capacity_penalty(amt_msat, e.get('capacity'))
                + self.disabled_penalty(e.get('fees'))
                + self.already_failed_penalty(e.get('channel_id')))
        return cost

    def add_bad_channel(self, channel, source, target):
        """
        Adds a channel to the blacklist dict.

        :param channel: channel_id
        :param source: pubkey
        :param target: pubkey
        """
        self.bad_channels[channel] = {
            'source': source,
            'target': target,
        }
        logger.debug(f"bad channels so far: {self.get_bad_channels()}")

    def add_bad_node(self, node_pub_key):
        """
        Adds a node public key to the blacklist.

        :param node_pub_key: str
        """
        self.bad_nodes.append(node_pub_key)
        logger.debug(f"bad nodes so far: {self.bad_nodes}")

    def get_bad_channels(self):
        return self.bad_channels.keys()

    def already_failed_penalty(self, channel_id):
        """
        Determines if the channel already failed at some point and penalizes it.

        :param channel_id:
        """
        # TODO: consider also direction
        if channel_id in self.get_bad_channels():
            return settings.PENALTY
        else:
            return 0

    @staticmethod
    def capacity_penalty(amt_msat, capacity_sat):
        """
        Gives a penalty to channels which have too low capacity.

        :param amt_msat
        :param capacity_sat in sat
        :return: penalty
        """
        if capacity_sat < 0.50 * amt_msat // 1000 :
            return settings.PENALTY
        else:
            return 0

    @staticmethod
    def disabled_penalty(policy):
        """
        Gives a penalty to channels which are not active.

        :param policy: policy of the channel, contains state
        :return: high penalty
        """
        if policy['disabled']:
            return settings.PENALTY
        else:
            return 0

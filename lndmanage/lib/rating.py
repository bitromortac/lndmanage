from collections import defaultdict, OrderedDict

from lndmanage import settings
from lndmanage.lib.exceptions import RouterRPCError

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


class NodeRater(object):
    """
    Rates nodes in the network.
    """
    def __init__(self, node):
        """
        :param node: ln node object
        :type node: lndmanage.lib.node.LndNode
        """
        self.node = node
        self.rated_nodes = defaultdict(
            lambda: {
                'good_channels': 0,
                'bad_channels': 0,
                'total_channels': None,
                'good_fraction': 0.0,
                'certainty': 0.0,
            })

    def rate_nodes(self):
        """
        Rates nodes based on mission control data.

        LND records for every payment attempt the failure or success
        of that payment on the individual parts of the route in its so-called
        mission control. This data can be queried by the routerrpc. A channel
        reliability score can be developped by counting how often a node
        was involved in positive or negative scenarios.

        :return: rated nodes
        :rtype: dict
        """
        try:
            pair_history = self.node.query_missioncontrol()

            if len(pair_history) < 2 * self.node.num_active_channels:
                logger.warning(
                    f"Found less than two payment pairs per active "
                    f"channel ({len(pair_history)} pairs found).\n"
                    f"This usually means that the channel reliability "
                    f"score is not accurate.\nDo some rebalancing first "
                    f"to learn about the network.")
            else:
                logger.info(f"Found {len(pair_history)} payment history pairs"
                            f" in mission control.")
        except RouterRPCError:
            logger.warning("Cannot calculate channel reliabilities because "
                           "routerrpc server is not enabled.")
            pair_history = {}

        if len(pair_history) == 0:
            return {}

        # do statistics for the individual nodes
        for node_pair, history in pair_history.items():
            # if a payment was successful, mark nodes having a good channel
            if history['last_attempt_successful']:
                self.rated_nodes[node_pair[0]]['good_channels'] += 1
                self.rated_nodes[node_pair[1]]['good_channels'] += 1
            # if a payment was not successful, mark nodes having a bad channel
            else:
                self.rated_nodes[node_pair[0]]['bad_channels'] += 1
                self.rated_nodes[node_pair[1]]['bad_channels'] += 1

        # add total number of channels
        for pubkey, stats in self.rated_nodes.items():
            self.rated_nodes[pubkey]['total_channels'] = \
                self.node.network.number_channels(pubkey)

        discard_nodes = []

        # weights for the channel reliability score:
        # most weight is given to nodes with good ratio of good channels
        # to bad channels
        weight_channel_ratio = 1.0
        # weight is given to nodes where we know we have more accurate data
        weight_certainty = 0.5
        # the total number of good channels indicates success for routing
        weight_good_channels = 0.03

        # construct channel reliability score
        for pubkey, stats in self.rated_nodes.items():
            total_rated_channels = stats['good_channels'] + stats['bad_channels']
            try:
                good_fraction = stats['good_channels'] / total_rated_channels
                certainty = total_rated_channels / stats['total_channels']
                # The reliability score consists of three components
                # (i)   The fraction of good versus bad channels,
                # (ii)  The certainty, which tells about how many of the node's
                #       channels were already rated.
                # (iii) The overall number of good channels.
                reliability = (weight_channel_ratio * good_fraction +
                               weight_certainty * certainty +
                               weight_good_channels * stats['good_channels'])
                self.rated_nodes[pubkey]['good_fraction'] = good_fraction
                self.rated_nodes[pubkey]['certainty'] = certainty
                self.rated_nodes[pubkey]['channel_reliability'] = reliability
            except ZeroDivisionError:
                discard_nodes.append(pubkey)

        logger.debug(f"Discarded nodes due to missing data: f{discard_nodes}")
        for node in discard_nodes:
            del self.rated_nodes[node]

        # sort the nodes for debugging purposes by channel reliability
        key_values = [(k, v) for k, v in self.rated_nodes.items()]
        sorted_key_values = sorted(
            key_values, reverse=True,key=lambda x: x[1]['channel_reliability'])
        ordered_nodes = OrderedDict(sorted_key_values)

        # renormalize with respect to most reliable node (usually our node)
        renormalization = max([
            n['channel_reliability'] for n in ordered_nodes.values()])
        for pubkey, stats in ordered_nodes.items():
            ordered_nodes[pubkey]['channel_reliability'] /= renormalization

        for pubkey, stats in ordered_nodes.items():
            logger.debug(
                f"{pubkey}, good chans: {stats['good_channels']}, "
                f"bad chans: {stats['bad_channels']}, "
                f"tot chans: {stats['total_channels']}, "
                f"good frac: {round(stats['good_fraction'], 2)}, "
                f"certainty: {round(stats['certainty'], 2)}, "
                f"channel reliability: "
                f"{round(stats['channel_reliability'], 2)}, "
            )

        return ordered_nodes


if __name__ == '__main__':
    from lndmanage.lib.node import LndNode
    nd = LndNode(config_file='')
    rd = NodeRater(nd)
    rd.rate_nodes()

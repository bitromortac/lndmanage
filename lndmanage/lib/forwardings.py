import logging
from collections import OrderedDict, defaultdict

import numpy as np

from lndmanage.lib.node import LndNode
from lndmanage import settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

np.warnings.filterwarnings('ignore')

# nearest neighbor weight for flow-analysis ~1/(avg. degree)
NEIGHBOR_WEIGHT = 0.1
# nearest neighbor weight for flow-analysis ~1/(avg. degree)^2
NEXT_NEIGHBOR_WEIGHT = 0.02


def nan_to_zero(number):
    """
    Converts float('nan') to 0
    :param number: float
    :return: float
    """
    if number is np.nan or number != number:
        return 0.0
    else:
        return number


class ForwardingAnalyzer(object):
    """
    Analyzes forwardings for single channels.
    """
    def __init__(self, node):
        self.node = node
        self.forwarding_events = self.node.get_forwarding_events()
        self.channels = {}
        self.total_forwarding_amount_sat = 0
        self.total_forwarding_fees_msat = 0
        self.forwardings = 0
        self.cumulative_effective_fee = 0
        self.timestamp_first_send = 1E10  # somewhere in future
        self.timestamp_last_send = 0  # at beginning of time
        self.max_time_interval = None

    def initialize_forwarding_data(self, time_start, time_end):
        """
        Initializes the channel statistics objects with data from
        the forwardings.

        :param time_start: time interval start, unix timestamp
        :param time_end: time interval end, unix timestamp
        """
        for f in self.forwarding_events:
            if time_start < f['timestamp'] < time_end:
                # make a dictionary entry for unknown channels
                channel_id_in = f['chan_id_in']
                channel_id_out = f['chan_id_out']

                if channel_id_in not in self.channels.keys():
                    self.channels[channel_id_in] = ChannelStatistics(
                        channel_id_in)
                if channel_id_out not in self.channels.keys():
                    self.channels[channel_id_out] = ChannelStatistics(
                        channel_id_out)

                self.channels[channel_id_in].inward_forwardings.append(
                    f['amt_in'])
                self.channels[channel_id_out].outward_forwardings.append(
                    f['amt_out'])
                self.channels[channel_id_out].absolute_fees.append(
                    f['fee_msat'])
                self.channels[channel_id_out].effective_fees.append(
                    f['effective_fee'])
                self.channels[channel_id_out].timestamps.append(
                    f['timestamp'])

                self.total_forwarding_amount_sat += f['amt_in']
                self.total_forwarding_fees_msat += f['fee_msat']
                self.forwardings += 1
                self.cumulative_effective_fee += f['effective_fee']

    def get_forwarding_statistics_channels(self):
        """
        Prepares the forwarding statistics for each channel.
        :return: dict: statistics with channel_id as keys
        """
        channel_statistics = {}

        for k, c in self.channels.items():

            try:
                timestamp_first_send = min(c.timestamps)
                if self.timestamp_first_send > timestamp_first_send:
                    self.timestamp_first_send = timestamp_first_send
            except ValueError:
                pass
            try:
                timestamp_last_send = max(c.timestamps)
                if self.timestamp_last_send < timestamp_last_send:
                    self.timestamp_last_send = timestamp_last_send
            except ValueError:
                pass

            channel_statistics[k] = {
                'effective_fee': c.effective_fee(),
                'fees_total': c.fees_total(),
                'flow_direction': c.flow_direction(),
                'mean_forwarding_in': c.mean_forwarding_in(),
                'mean_forwarding_out': c.mean_forwarding_out(),
                'median_forwarding_in': c.median_forwarding_in(),
                'median_forwarding_out': c.median_forwarding_out(),
                'number_forwardings': c.number_forwardings(),
                'largest_forwarding_amount_in':
                    c.largest_forwarding_amount_in(),
                'largest_forwarding_amount_out':
                    c.largest_forwarding_amount_out(),
                'total_forwarding_in': c.total_forwarding_in(),
                'total_forwarding_out': c.total_forwarding_out(),
            }

        # determine the time interval starting with the first forwarding
        # to the last forwarding in the analyzed time interval determined
        # by time_start and time_end
        self.max_time_interval = \
            (self.timestamp_last_send - self.timestamp_first_send) \
            / (24 * 60 * 60)

        return channel_statistics

    def get_forwarding_statistics_nodes(self, sort_by='total_forwarding'):
        """
        Calculates forwarding statistics based on single channels for
        their nodes.

        :param sort_by: str, abbreviation for the dict key
        :return:
        """
        channel_statistics = self.get_forwarding_statistics_channels()
        closed_channels = self.node.get_closed_channels()
        open_channels = self.node.get_open_channels()
        logger.debug(f"Number of channels with known forwardings: "
                     f"{len(closed_channels) + len(open_channels)} "
                     f"(thereof {len(closed_channels)} closed channels).")

        node_statistics = OrderedDict()

        # go through channel statistics and calculate node statistics
        for k, n in channel_statistics.items():
            # historic node data can be outdated, so we need to take care
            # that the remote pub key is known,
            # otherwise it is useless information

            channel_data = open_channels.get(k, None)
            if not channel_data:
                channel_data = closed_channels.get(k, None)

            if channel_data:
                remote_pubkey = channel_data['remote_pubkey']
                if remote_pubkey not in node_statistics.keys():
                    node_statistics[remote_pubkey] = {
                        'total_forwarding_in': n['total_forwarding_in'],
                        'total_forwarding_out': n['total_forwarding_out'],
                        'total_forwarding':
                            n['total_forwarding_in'] +
                            n['total_forwarding_out'],
                    }
                else:
                    node_statistics[remote_pubkey]['total_forwarding_in'] \
                        += n['total_forwarding_in']
                    node_statistics[remote_pubkey]['total_forwarding_out'] \
                        += n['total_forwarding_out']
                    node_statistics[remote_pubkey]['total_forwarding'] \
                        += (n['total_forwarding_in'] +
                            n['total_forwarding_out'])

        for k, n in node_statistics.items():
            tot_in = n['total_forwarding_in']
            tot_out = n['total_forwarding_out']
            node_statistics[k]['flow_direction'] = \
                -((float(tot_in) / (tot_in + tot_out)) - 0.5) / 0.5

        sorted_dict = OrderedDict(
            sorted(node_statistics.items(), key=lambda x: -x[1][sort_by]))

        return sorted_dict

    def simple_flow_analysis(self, last_forwardings_to_analyze=100):
        """
        Takes each forwarding event and determines the set of incoming nodes
        (up to second nearest neighbors) and outgoing nodes
        (up to second nearest neighbors) and does a frequency analysis of both
        sets, assigning a probability that a certain node was involved in
        the forwarding process.

        These probabilities are then used to take the difference between
        both, excluding effectively the large hubs. The sets can be weighted
        by a quantity of the forwarding process, e.g. the forwarding fee.

        Two lists are returned, the rest of the incoming and the rest of the
        outgoing node sets.

        :param last_forwardings_to_analyze:
            number of last forwardings to be analyzed
        :type last_forwardings_to_analyze: int

        :return: sending list, receiving list
        """
        # TODO: refine with channel capacities
        # TODO: refine with update time
        # TODO: refine with route calculation
        # TODO: fine tune NEIGHBOR_WEIGHT, NEXT_NEIGHBOR_WEIGHT

        logger.info("Doing simple forwarding analysis.")

        # initialize node score dictionaries
        total_incoming_neighbors = defaultdict(float)
        total_outgoing_neighbors = defaultdict(float)

        logger.info(f"Total forwarding events found: "
                    f"{len(self.forwarding_events)}.")
        logger.info(f"Carrying out flow analysis for last "
                    f"{last_forwardings_to_analyze} forwarding events.")
        number_progress_report = last_forwardings_to_analyze // 10

        meaningful_outward_forwardings = 0
        for nf, f in enumerate(
                self.forwarding_events[-last_forwardings_to_analyze:]):

            # report progress
            if nf % number_progress_report == 0:
                logger.info(
                    f"Analysis progress: "
                    f"{100 * float(nf) / last_forwardings_to_analyze}%")

            chan_id_in = f['chan_id_in']
            chan_id_out = f['chan_id_out']

            edge_data_in = self.node.network.edges.get(chan_id_in, None)
            edge_data_out = self.node.network.edges.get(chan_id_out, None)

            if edge_data_in is not None and edge_data_out is not None:
                # determine incoming and outgoing node pub keys
                incoming_node_pub_key = edge_data_in['node1_pub'] \
                    if edge_data_in['node1_pub'] != self.node.pub_key \
                    else edge_data_in['node2_pub']
                outgoing_node_pub_key = edge_data_out['node1_pub'] \
                    if edge_data_out['node1_pub'] != self.node.pub_key \
                    else edge_data_out['node2_pub']

                # nodes involved in the forwarding process should be excluded
                excluded_nodes = [self.node.pub_key, incoming_node_pub_key,
                    outgoing_node_pub_key]

                # determine all the nearest and second nearest
                # neighbors of the incoming/outgoing nodes,
                # they may appear more than once
                incoming_neighbors = self.__determine_joined_neighbors(
                    incoming_node_pub_key, excluded_nodes=excluded_nodes)
                outgoing_neighbors = self.__determine_joined_neighbors(
                    outgoing_node_pub_key, excluded_nodes=excluded_nodes)

                # do a symmetric difference of node sets with weights
                symmetric_difference_weights = self.__symmetric_difference(
                    incoming_neighbors, outgoing_neighbors)

                final_outgoing_nodes = self.__filter_nodes(
                    symmetric_difference_weights,
                    return_positive_weights=True)
                final_incoming_nodes = self.__filter_nodes(
                    symmetric_difference_weights,
                    return_positive_weights=False)

                # normalize the weights
                normalized_incoming = self.__normalize_neighbors(
                    final_incoming_nodes)
                normalized_outgoing = self.__normalize_neighbors(
                    final_outgoing_nodes)

                # set weight for each forwarding event
                weight = 1
                # alternatively:
                # weight = f['amt_in']
                # weight = f['fee_msat']

                for n, nv in normalized_incoming.items():
                    total_incoming_neighbors[n] += nv * weight

                # If we know, that the outward hop already reached the
                # target of the payment, we don't want to add the neighbors
                # of the outgoing node to the total statistics.
                # We know if the next hop was the final one of the payment by
                # testing whether the forwarding amount in msat has remainder
                # zero when divided by 1000 or not, provided the sent amount
                # was larger than 1E6 msat.
                if (f['amt_out_msat'] % 1000):
                    meaningful_outward_forwardings += 1
                    logger.debug(
                        f"Forwarding was not last hop: {f['amt_out_msat']}, "
                        f"chan_id_out: {chan_id_out}")
                    for n, nv in normalized_outgoing.items():
                        total_outgoing_neighbors[n] += nv * weight
        logger.info(f"Could use {meaningful_outward_forwardings} "
                    f"forwardings to estimate targets of payments.")

        # sort according to weights
        total_incoming_node_dict = self.__weighted_neighbors_to_sorted_dict(
            total_incoming_neighbors)
        total_outgoing_node_dict = self.__weighted_neighbors_to_sorted_dict(
            total_outgoing_neighbors)

        return total_incoming_node_dict, total_outgoing_node_dict

    @staticmethod
    def __weighted_neighbors_to_sorted_dict(node_dict):
        """
        Converts a node weight dictionary to a sorted list of
        nodes with weights.

        :param node_dict: dict with key-value pairs of node_pub_key and weight
        :return: sorted list
        """
        sorted_nodes_dict = OrderedDict()
        node_list = [(n, nv) for n, nv in node_dict.items()]
        node_list_sorted = sorted(node_list, key=lambda x: x[1], reverse=True)
        for n, nv in node_list_sorted:
            sorted_nodes_dict[n] = {'weight': nv}
        return sorted_nodes_dict

    def __determine_joined_neighbors(self, node_pub_key, excluded_nodes):
        """
        Determines the joined set of nearest and second neighbors and assigns
        a weight to every node dependent how often they appear.

        :param node_pub_key: str, public key of the home node
        :param excluded_nodes: list of str, public keys of excluded nodes
                                            in analysis
        :return: dict, keys: node_pub_keys, values: weights
        """

        neighbors = list(self.node.network.neighbors(node_pub_key))
        second_neighbors = list(
            self.node.network.second_neighbors(node_pub_key))

        # determine neighbor node_weights
        neighbor_weights = self.__analyze_neighbors(
            neighbors, excluded_nodes=excluded_nodes, weight=NEIGHBOR_WEIGHT)
        second_neighbor_weights = self.__analyze_neighbors(
            second_neighbors, excluded_nodes=excluded_nodes,
            weight=NEXT_NEIGHBOR_WEIGHT)

        # combine nearest and second nearest neighbor node weights
        joined_neighbors = self.__join_neighbors(
            neighbor_weights, second_neighbor_weights)

        return joined_neighbors

    @staticmethod
    def __normalize_neighbors(neighbors_weight_dict):
        """
        Normalizes the weights of the neighbors to the total weight
        of all neighbors.

        :param neighbors_weight_dict: dict, keys: node_pub_keys,
                                            values: weights
        :return: dict, keys: node_pub_keys, values: normalized weights
        """
        total_weight = 0
        normalized_dict = {}
        # determine total weight
        for n, nv in neighbors_weight_dict.items():
            total_weight += nv
        # normalize
        for n, nv in neighbors_weight_dict.items():
            normalized_dict[n] = float(nv) / total_weight

        return normalized_dict

    @staticmethod
    def __analyze_neighbors(neighbors, excluded_nodes, weight):
        """
        Analyzes a node dict for the frequency of nodes and gives them
        a weight. An upper bound of the weights is set.

        :param neighbors: list of node_pub_keys
        :param excluded_nodes: excluded node_pub_keys for analysis
        :param weight: float, weight for each individual appearance of a node
        :return: dict, keys: node_pub_keys, values: node weights
        """
        node_weights = {}

        for n in neighbors:
            if n not in excluded_nodes:
                if n in node_weights.keys():
                    node_weights[n] = min(node_weights[n] + weight, 1.0)
                else:
                    node_weights[n] = weight

        return node_weights

    @staticmethod
    def __join_neighbors(first_neighbor_dict, second_neighbor_dict):
        """
        Joins two node weight dicts together.
        :param first_neighbor_dict: dict, keys: node_pub_keys,
                                          values: node weights
        :param second_neighbor_dict: dict, keys: node_pub_keys,
                                           values: node weights
        :return: dict, keys: node_pub_keys, values: node weights
        """
        # make a copy of the first node weight dict
        joined_neighbor_dict = dict(first_neighbor_dict)

        # add all the nodes from the second dict
        for n, v in second_neighbor_dict.items():
            if n in joined_neighbor_dict:
                joined_neighbor_dict[n] = min(
                    1, joined_neighbor_dict[n] + second_neighbor_dict[n])
            else:
                joined_neighbor_dict[n] = second_neighbor_dict[n]

        return joined_neighbor_dict

    @staticmethod
    def __symmetric_difference(first_neighbors_dict, second_neighbors_dict):
        """
        Calculates the difference of weights of first and second node dicts,
        doing also a symmetric difference between the sets of nodes.

        :param first_neighbors_dict: dict, keys: node_pub_keys,
                                           values: node weights
        :param second_neighbors_dict: dict, keys: node_pub_keys,
                                            values: node weights
        :return: dict, keys: node_pub_keys, values: node weights
        """
        first_nodes = set(first_neighbors_dict.keys())
        second_nodes = set(second_neighbors_dict.keys())

        nodes_intersection = first_nodes.intersection(second_nodes)

        unique_first_nodes = first_nodes - nodes_intersection
        unique_second_nodes = second_nodes - nodes_intersection

        diff_neighbor_dict = {}
        for n in unique_first_nodes:
            diff_neighbor_dict[n] = first_neighbors_dict[n]

        for n in unique_second_nodes:
            diff_neighbor_dict[n] = second_neighbors_dict[n]

        for n in nodes_intersection:
            delta = first_neighbors_dict[n] - second_neighbors_dict[n]
            if delta != 0.0:
                diff_neighbor_dict[n] = delta

        return diff_neighbor_dict

    @staticmethod
    def __filter_nodes(node_weights, return_positive_weights=True):
        """
        Filters out nodes with positive or negative weights and
        takes the absolute.

        :param node_weights: dict
        :param return_positive_weights: bool, if True returns nodes with
                                              positive weights,
                                              if False negative weights
        :return:
        """
        new_node_weights = {}
        for n, nv in node_weights.items():
            if nv > 0 and return_positive_weights:
                new_node_weights[n] = nv
            elif nv < 0 and not return_positive_weights:
                new_node_weights[n] = -nv
        return new_node_weights


class ChannelStatistics(object):
    """
    Functionality to analyze the forwardings of a single channel.
    """
    def __init__(self, channel_id):
        self.channel_id = channel_id

        self.inward_forwardings = []
        self.outward_forwardings = []

        self.timestamps = []
        self.absolute_fees = []
        self.effective_fees = []

    def total_forwarding_in(self):
        return sum(self.inward_forwardings)

    def total_forwarding_out(self):
        return sum(self.outward_forwardings)

    def mean_forwarding_in(self):
        return np.mean(self.inward_forwardings)

    def mean_forwarding_out(self):
        return np.mean(self.outward_forwardings)

    def median_forwarding_in(self):
        return np.median(self.inward_forwardings)

    def median_forwarding_out(self):
        return np.median(self.outward_forwardings)

    def fees_total(self):
        return sum(self.absolute_fees)

    def effective_fee(self):
        return np.mean(self.effective_fees)

    def largest_forwarding_amount_out(self):
        return max(self.outward_forwardings, default=float('nan'))

    def largest_forwarding_amount_in(self):
        return max(self.inward_forwardings, default=float('nan'))

    def flow_direction(self):
        total_in = self.total_forwarding_in()
        total_out = self.total_forwarding_out()
        return -((float(total_in) / (total_in + total_out)) - 0.5) / 0.5

    def number_forwardings(self):
        return len(self.inward_forwardings) + len(self.outward_forwardings)


def get_forwarding_statistics_channels(node, time_interval_start,
                                       time_interval_end):
    """
    Joins data from listchannels and fwdinghistory to have a extended
    information about a channel.

    :param node: :class:`lib.node.Node`
    :param time_interval_start: unix timestamp
    :param time_interval_end: unix timestamp
    :return: dict of channel information with channel_id as keys
    """
    forwarding_analyzer = ForwardingAnalyzer(node)
    forwarding_analyzer.initialize_forwarding_data(
        time_interval_start, time_interval_end)

    # dict with channel_id keys
    statistics = forwarding_analyzer.get_forwarding_statistics_channels()
    logger.debug(f"Time interval (between first and last forwarding) is "
                 f"{forwarding_analyzer.max_time_interval:6.2f} days.")
    # join the two data sets:
    channels = node.get_unbalanced_channels(unbalancedness_greater_than=0.0)

    # TODO: improve this code, don't repeat
    for k, c in channels.items():
        try:  # channel forwarding statistics exists
            chan_stats = statistics[c['chan_id']]
            c['bandwidth_demand'] = max(
                nan_to_zero(chan_stats['mean_forwarding_in']),
                nan_to_zero(chan_stats['mean_forwarding_out'])
            ) / c['capacity']
            c['fees_total'] = chan_stats['fees_total']
            # time interval may be zero, to avoid zero division, replace by NaN
            try:
                c['fees_total_per_week'] = chan_stats['fees_total'] \
                    / (forwarding_analyzer.max_time_interval / 7)
            except ZeroDivisionError:
                c['fees_total_per_week'] = float('nan')
            c['flow_direction'] = chan_stats['flow_direction']
            c['median_forwarding_in'] = chan_stats['median_forwarding_in']
            c['median_forwarding_out'] = chan_stats['median_forwarding_out']
            c['mean_forwarding_in'] = chan_stats['mean_forwarding_in']
            c['mean_forwarding_out'] = chan_stats['mean_forwarding_out']
            c['number_forwardings'] = chan_stats['number_forwardings']
            c['largest_forwarding_amount_in'] = \
                chan_stats['largest_forwarding_amount_in']
            c['largest_forwarding_amount_out'] = \
                chan_stats['largest_forwarding_amount_out']
            c['total_forwarding_in'] = chan_stats['total_forwarding_in']
            c['total_forwarding_out'] = chan_stats['total_forwarding_out']

            # action required if flow same direction as unbalancedness
            # or bandwidth demand too high

            # TODO: refine 'action_required' by better metric
            if c['unbalancedness'] * c['flow_direction'] > 0 and abs(
                    c['unbalancedness']) > settings.UNBALANCED_CHANNEL:
                c['action_required'] = True
            else:
                c['action_required'] = False
            if c['bandwidth_demand'] > 0.5:
                c['action_required'] = True

        except KeyError:  # no forwarding statistics on channel is available
            c['bandwidth_demand'] = 0
            c['fees_total'] = 0
            c['fees_total_per_week'] = 0
            c['flow_direction'] = float('nan')
            c['median_forwarding_out'] = float('nan')
            c['median_forwarding_in'] = float('nan')
            c['mean_forwarding_out'] = float('nan')
            c['mean_forwarding_in'] = float('nan')
            c['number_forwardings'] = 0
            c['largest_forwarding_amount_in'] = float('nan')
            c['largest_forwarding_amount_out'] = float('nan')
            c['total_forwarding_in'] = float('nan')
            c['total_forwarding_out'] = float('nan')
            if abs(c['unbalancedness']) > settings.UNBALANCED_CHANNEL:
                c['action_required'] = True
            else:
                c['action_required'] = False
            if c['bandwidth_demand'] > 0.5:
                c['action_required'] = True
    return channels


if __name__ == '__main__':
    import time
    import logging.config
    logging.config.dictConfig(settings.logger_config)
    logger = logging.getLogger()

    nd = LndNode()
    fa = ForwardingAnalyzer(nd)
    fa.initialize_forwarding_data(time_start=0, time_end=time.time())
    print(fa.simple_flow_analysis())
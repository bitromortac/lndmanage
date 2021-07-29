"""Module for gathering statistics of channels or nodes."""
from collections import OrderedDict, defaultdict
import logging
from typing import Dict

import numpy as np

from lndmanage.lib.data_types import NodeProperties
from lndmanage.lib.node import LndNode
from lndmanage.lib.ln_utilities import channel_unbalancedness_and_commit_fee
from lndmanage import settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

np.warnings.filterwarnings("ignore")

# nearest neighbor weight for flow-analysis ~1/(avg. degree)
NEIGHBOR_WEIGHT = 0.1
# nearest neighbor weight for flow-analysis ~1/(avg. degree)^2
NEXT_NEIGHBOR_WEIGHT = 0.02


def nan_to_zero(number: float) -> float:
    if number is np.nan or number != number:
        return 0.0
    else:
        return number


class ForwardingAnalyzer(object):
    """Analyzes forwardings for single channels."""

    def __init__(self, node: "LndNode"):
        self.node = node
        self.forwarding_events = self.node.get_forwarding_events()
        self.channel_forwarding_stats = {}  # type: Dict[str, ForwardingStatistics]
        self.node_forwarding_stats = {}  # type: Dict[str, ForwardingStatistics]
        self.max_time_interval_days = None

    def initialize_forwarding_stats(self, time_start: float, time_end: float):
        """Initializes the channel and node statistics objects with data from forwardings.

        :param time_start: time interval start, unix timestamp
        :param time_end: time interval end, unix timestamp
        """
        channel_id_to_node_id = self.node.get_channel_id_to_node_id()
        self.channel_forwarding_stats = defaultdict(ForwardingStatistics)
        self.node_forwarding_stats = defaultdict(ForwardingStatistics)

        min_timestamp = float("inf")
        max_timestamp = 0
        for f in self.forwarding_events:
            if time_start < f["timestamp"] < time_end:
                # find min and max range of forardings
                if f["timestamp"] > max_timestamp:
                    max_timestamp = f["timestamp"]
                if f["timestamp"] < min_timestamp:
                    min_timestamp = f["timestamp"]
                # make a dictionary entry for unknown channels
                channel_id_in = f["chan_id_in"]
                channel_id_out = f["chan_id_out"]
                node_id_in = channel_id_to_node_id.get(channel_id_in)
                node_id_out = channel_id_to_node_id.get(channel_id_out)

                # node statistics
                if node_id_in:
                    self.node_forwarding_stats[node_id_in].inward_forwardings.append(
                        f["amt_in"]
                    )
                if node_id_out:
                    self.node_forwarding_stats[node_id_out].outward_forwardings.append(
                        f["amt_out"]
                    )
                    self.node_forwarding_stats[node_id_out].absolute_fees.append(
                        f["fee_msat"]
                    )
                    self.node_forwarding_stats[node_id_out].effective_fees.append(
                        f["effective_fee"]
                    )
                    self.node_forwarding_stats[node_id_out].timestamps.append(
                        f["timestamp"]
                    )

                # channel statistics
                self.channel_forwarding_stats[channel_id_in].inward_forwardings.append(
                    f["amt_in"]
                )
                self.channel_forwarding_stats[
                    channel_id_out
                ].outward_forwardings.append(f["amt_out"])
                self.channel_forwarding_stats[channel_id_out].absolute_fees.append(
                    f["fee_msat"]
                )
                self.channel_forwarding_stats[channel_id_out].effective_fees.append(
                    f["effective_fee"]
                )
                self.channel_forwarding_stats[channel_id_out].timestamps.append(
                    f["timestamp"]
                )

        # determine the time interval starting with the first forwarding
        # to the last forwarding in the analyzed time interval determined
        # by time_start and time_end
        self.max_time_interval_days = (max_timestamp - min_timestamp) / (24 * 60 * 60)

    def get_forwarding_statistics_channels(self):
        """Prepares the forwarding statistics for each channel.

        :return: dict: statistics with channel_id as keys
        """
        channel_statistics = {}

        for k, c in self.channel_forwarding_stats.items():
            channel_statistics[k] = {
                "effective_fee": c.effective_fee(),
                "fees_total": c.fees_total(),
                "flow_direction": c.flow_direction(),
                "mean_forwarding_in": c.mean_forwarding_in(),
                "mean_forwarding_out": c.mean_forwarding_out(),
                "median_forwarding_in": c.median_forwarding_in(),
                "median_forwarding_out": c.median_forwarding_out(),
                "number_forwardings": c.number_forwardings(),
                "number_forwardings_out": c.number_forwardings_out(),
                "largest_forwarding_amount_in": c.largest_forwarding_amount_in(),
                "largest_forwarding_amount_out": c.largest_forwarding_amount_out(),
                "total_forwarding_in": c.total_forwarding_in(),
                "total_forwarding_out": c.total_forwarding_out(),
            }
        return channel_statistics

    def get_forwarding_statistics_nodes(self, sort_by="total_forwarding"):
        """Calculates forwarding statistics based on individual channels for
        their nodes.

        :param sort_by: str, abbreviation for the dict key
        :return:
        """
        closed_channels = self.node.get_closed_channels()
        open_channels = self.node.get_open_channels()
        logger.debug(
            f"Number of channels with known forwardings: "
            f"{len(closed_channels) + len(open_channels)} "
            f"(thereof {len(closed_channels)} closed channels)."
        )

        forwarding_stats = defaultdict(dict)
        for nid, node_stats in self.node_forwarding_stats.items():
            tot_in = node_stats.total_forwarding_in()
            tot_out = node_stats.total_forwarding_out()
            forwarding_stats[nid]["effective_fee"] = node_stats.effective_fee()
            forwarding_stats[nid]["fees_total"] = node_stats.fees_total()
            forwarding_stats[nid]["flow_direction"] = (
                -((float(tot_in) / (tot_in + tot_out)) - 0.5) / 0.5
            )
            forwarding_stats[nid][
                "largest_forwarding_amount_in"
            ] = node_stats.largest_forwarding_amount_in()
            forwarding_stats[nid][
                "largest_forwarding_amount_out"
            ] = node_stats.largest_forwarding_amount_out()
            forwarding_stats[nid][
                "mean_forwarding_in"
            ] = node_stats.mean_forwarding_in()
            forwarding_stats[nid][
                "mean_forwarding_out"
            ] = node_stats.mean_forwarding_out()
            forwarding_stats[nid][
                "median_forwarding_in"
            ] = node_stats.median_forwarding_in()
            forwarding_stats[nid][
                "median_forwarding_out"
            ] = node_stats.median_forwarding_out()
            forwarding_stats[nid][
                "number_forwardings"
            ] = node_stats.number_forwardings()
            forwarding_stats[nid]["total_forwarding_in"] = tot_in
            forwarding_stats[nid]["total_forwarding_out"] = tot_out
            forwarding_stats[nid]["total_forwarding"] = tot_in + tot_out

        sorted_dict = OrderedDict(
            sorted(forwarding_stats.items(), key=lambda x: -x[1][sort_by])
        )

        return sorted_dict

    def simple_flow_analysis(self, last_forwardings_to_analyze=100):
        """Takes each forwarding event and determines the set of incoming nodes
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

        :return: sending list, receiving list"""
        # TODO: refine with channel capacities
        # TODO: refine with update time
        # TODO: refine with route calculation
        # TODO: fine tune NEIGHBOR_WEIGHT, NEXT_NEIGHBOR_WEIGHT

        logger.info("Doing simple forwarding analysis.")

        # initialize node score dictionaries
        total_incoming_neighbors = defaultdict(float)
        total_outgoing_neighbors = defaultdict(float)

        logger.info(
            f"Total forwarding events found: " f"{len(self.forwarding_events)}."
        )
        logger.info(
            f"Carrying out flow analysis for last "
            f"{last_forwardings_to_analyze} forwarding events."
        )
        number_progress_report = last_forwardings_to_analyze // 10

        meaningful_outward_forwardings = 0
        for nf, f in enumerate(self.forwarding_events[-last_forwardings_to_analyze:]):

            # report progress
            if nf % number_progress_report == 0:
                logger.info(
                    f"Analysis progress: "
                    f"{100 * float(nf) / last_forwardings_to_analyze}%"
                )

            chan_id_in = f["chan_id_in"]
            chan_id_out = f["chan_id_out"]

            edge_data_in = self.node.network.edges.get(chan_id_in, None)
            edge_data_out = self.node.network.edges.get(chan_id_out, None)

            if edge_data_in is not None and edge_data_out is not None:
                # determine incoming and outgoing node pub keys
                incoming_node_pub_key = (
                    edge_data_in["node1_pub"]
                    if edge_data_in["node1_pub"] != self.node.pub_key
                    else edge_data_in["node2_pub"]
                )
                outgoing_node_pub_key = (
                    edge_data_out["node1_pub"]
                    if edge_data_out["node1_pub"] != self.node.pub_key
                    else edge_data_out["node2_pub"]
                )

                # nodes involved in the forwarding process should be excluded
                excluded_nodes = [
                    self.node.pub_key,
                    incoming_node_pub_key,
                    outgoing_node_pub_key,
                ]

                # determine all the nearest and second nearest
                # neighbors of the incoming/outgoing nodes,
                # they may appear more than once
                incoming_neighbors = self.__determine_joined_neighbors(
                    incoming_node_pub_key, excluded_nodes=excluded_nodes
                )
                outgoing_neighbors = self.__determine_joined_neighbors(
                    outgoing_node_pub_key, excluded_nodes=excluded_nodes
                )

                # do a symmetric difference of node sets with weights
                symmetric_difference_weights = self.__symmetric_difference(
                    incoming_neighbors, outgoing_neighbors
                )

                final_outgoing_nodes = self.__filter_nodes(
                    symmetric_difference_weights, return_positive_weights=True
                )
                final_incoming_nodes = self.__filter_nodes(
                    symmetric_difference_weights, return_positive_weights=False
                )

                # normalize the weights
                normalized_incoming = self.__normalize_neighbors(final_incoming_nodes)
                normalized_outgoing = self.__normalize_neighbors(final_outgoing_nodes)

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
                if f["amt_out_msat"] % 1000:
                    meaningful_outward_forwardings += 1
                    logger.debug(
                        f"Forwarding was not last hop: {f['amt_out_msat']}, "
                        f"chan_id_out: {chan_id_out}"
                    )
                    for n, nv in normalized_outgoing.items():
                        total_outgoing_neighbors[n] += nv * weight
        logger.info(
            f"Could use {meaningful_outward_forwardings} "
            f"forwardings to estimate targets of payments."
        )

        # sort according to weights
        total_incoming_node_dict = self.__weighted_neighbors_to_sorted_dict(
            total_incoming_neighbors
        )
        total_outgoing_node_dict = self.__weighted_neighbors_to_sorted_dict(
            total_outgoing_neighbors
        )

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
            sorted_nodes_dict[n] = {"weight": nv}
        return sorted_nodes_dict

    def __determine_joined_neighbors(self, node_pub_key, excluded_nodes):
        """Determines the joined set of nearest and second neighbors and assigns
        a weight to every node dependent how often they appear.

        :param node_pub_key: str, public key of the home node
        :param excluded_nodes: list of str, public keys of excluded nodes
                                            in analysis
        :return: dict, keys: node_pub_keys, values: weights
        """

        neighbors = list(self.node.network.neighbors(node_pub_key))
        second_neighbors = list(self.node.network.second_neighbors(node_pub_key))

        # determine neighbor node_weights
        neighbor_weights = self.__analyze_neighbors(
            neighbors, excluded_nodes=excluded_nodes, weight=NEIGHBOR_WEIGHT
        )
        second_neighbor_weights = self.__analyze_neighbors(
            second_neighbors, excluded_nodes=excluded_nodes, weight=NEXT_NEIGHBOR_WEIGHT
        )

        # combine nearest and second nearest neighbor node weights
        joined_neighbors = self.__join_neighbors(
            neighbor_weights, second_neighbor_weights
        )

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
        """Joins two node weight dicts together.
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
                    1, joined_neighbor_dict[n] + second_neighbor_dict[n]
                )
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


class ForwardingStatistics(object):
    """Functionality to analyze the forwardings of a single node/channel."""

    def __init__(self):
        self.inward_forwardings = []
        self.outward_forwardings = []
        self.timestamps = []
        self.absolute_fees = []
        self.effective_fees = []

    def total_forwarding_in(self) -> int:
        return sum(self.inward_forwardings)

    def total_forwarding_out(self) -> int:
        return sum(self.outward_forwardings)

    def mean_forwarding_in(self) -> float:
        return np.mean(self.inward_forwardings)

    def mean_forwarding_out(self) -> float:
        return np.mean(self.outward_forwardings)

    def median_forwarding_in(self) -> float:
        return np.median(self.inward_forwardings)

    def median_forwarding_out(self) -> float:
        return np.median(self.outward_forwardings)

    def fees_total(self) -> int:
        return sum(self.absolute_fees)

    def effective_fee(self) -> float:
        return np.mean(self.effective_fees)

    def largest_forwarding_amount_out(self) -> int:
        return max(self.outward_forwardings, default=float("nan"))

    def largest_forwarding_amount_in(self) -> int:
        return max(self.inward_forwardings, default=float("nan"))

    def flow_direction(self) -> float:
        total_in = self.total_forwarding_in()
        total_out = self.total_forwarding_out()
        try:
            return (-total_in + total_out) / (total_in + total_out)
        except ZeroDivisionError:
            return 0

    def number_forwardings(self) -> int:
        return len(self.inward_forwardings) + len(self.outward_forwardings)

    def number_forwardings_out(self):
        return len(self.outward_forwardings)


def get_node_properites(
    node: LndNode, time_interval_start: float, time_interval_end: float
) -> Dict:
    """Joins data from channels and fwdinghistory to have extended
    information about a node.

    :return: dict of node information with channel_id as keys
    """
    forwarding_analyzer = ForwardingAnalyzer(node)
    forwarding_analyzer.initialize_forwarding_stats(
        time_interval_start, time_interval_end
    )
    node_forwarding_statistics = forwarding_analyzer.get_forwarding_statistics_nodes()
    logger.debug(
        f"Time interval (between first and last forwarding) is "
        f"{forwarding_analyzer.max_time_interval_days:6.2f} days."
    )
    channel_id_to_node_id = node.get_channel_id_to_node_id(open_only=True)
    node_ids_with_open_channels = {nid for nid in channel_id_to_node_id.values()}
    open_channels = node.get_open_channels()

    nodes_properties = {}  # type: Dict[str, NodeProperties]

    # for each channel, accumulate properties in node properties
    for k, c in open_channels.items():
        remote_pubkey = c["remote_pubkey"]
        try:
            properties = nodes_properties[remote_pubkey]
        except KeyError:
            nodes_properties[remote_pubkey] = NodeProperties(
                age=c["age"],
                local_fee_rates=[c["local_fee_rate"]],
                local_base_fees=[c["local_base_fee"]],
                local_balances=[c["local_balance"]],
                number_active_channels=1 if c["active"] else 0,
                number_channels=1,
                number_private_channels=1 if c["private"] else 0,
                remote_fee_rates=[c["peer_fee_rate"]],
                remote_base_fees=[c["peer_base_fee"]],
                remote_balances=[c["remote_balance"]],
                sent_received_per_week=c["sent_received_per_week"],
                public_capacities=[c["capacity"]] if not c["private"] else [],
                private_capacites=[c["capacity"]] if c["private"] else [],
            )
        else:
            properties.age = max(c["age"], nodes_properties[c["remote_pubkey"]].age)
            properties.local_fee_rates.append(c["local_fee_rate"])
            properties.local_base_fees.append(c["local_base_fee"])
            properties.local_balances.append(c["local_balance"])
            properties.number_active_channels += 1 if c["active"] else 0
            properties.number_channels += 1
            properties.number_private_channels += 1 if c["private"] else 0
            properties.remote_fee_rates.append(c["peer_fee_rate"])
            properties.remote_base_fees.append(c["peer_base_fee"])
            properties.remote_balances.append(c["remote_balance"])
            properties.sent_received_per_week += c["sent_received_per_week"]
            if not c["private"]:
                properties.public_capacities.append(c["capacity"])
            else:
                properties.private_capacites.append(c["capacity"])

    # unify node properties with forwarding data
    node_properties_forwardings = {}
    # we start with looping over node properties, as this info is complete
    for node_id, properties in nodes_properties.items():
        local_balance = sum(properties.local_balances)
        remote_balance = sum(properties.remote_balances)
        capacity = sum(properties.private_capacites) + sum(properties.public_capacities)
        # there can be old forwarding data, which we neglect
        if node_id not in node_ids_with_open_channels:
            continue

        # initial data:
        node_properties_forwardings[node_id] = {
            "age": properties.age,
            "alias": node.network.node_alias(node_id),
            "local_base_fee": np.median(properties.local_base_fees),
            "local_fee_rate": np.median(properties.local_fee_rates),
            "local_balance": local_balance,
            "max_local_balance": max(properties.local_balances),
            "max_remote_balance": max(properties.remote_balances),
            "number_channels": properties.number_channels,
            "number_active_channels": properties.number_active_channels,
            "number_private_channels": properties.number_private_channels,
            "node_id": node_id,
            "remote_base_fee": np.median(properties.remote_base_fees),
            "remote_fee_rate": np.median(properties.remote_fee_rates),
            "remote_balance": remote_balance,
            "sent_reveived_per_week": properties.sent_received_per_week,
            "total_capacity": capacity,
            "max_public_capacity": max(properties.public_capacities)
            if properties.public_capacities
            else 0,
            "unbalancedness": channel_unbalancedness_and_commit_fee(
                local_balance, capacity, 0, False
            )[0],
        }

        # add forwarding data if available:
        try:
            statistics = node_forwarding_statistics[node_id]
        except KeyError:  # we don't have forwarding data, populate with defaults
            node_properties_forwardings[node_id].update(
                {
                    "effective_fee": float("nan"),
                    "fees_total": 0,
                    "flow_direction": float("nan"),
                    "largest_forwarding_amount_in": float("nan"),
                    "largest_forwarding_amount_out": float("nan"),
                    "median_forwarding_out": float("nan"),
                    "median_forwarding_in": float("nan"),
                    "mean_forwarding_out": float("nan"),
                    "mean_forwarding_in": float("nan"),
                    "number_forwardings": 0,
                    "total_forwarding_in": 0,
                    "total_forwarding_out": 0,
                    "total_forwarding": 0,
                }
            )
        else:
            node_properties_forwardings[node_id].update(**statistics)

        try:
            node_properties_forwardings[node_id][
                "fees_total_per_week"
            ] = node_properties_forwardings[node_id]["fees_total"] / (
                forwarding_analyzer.max_time_interval_days / 7
            )
        except ZeroDivisionError:
            node_properties_forwardings[node_id]["fees_total_per_week"] = float("nan")

    return node_properties_forwardings


def get_channel_properties(
    node: LndNode, time_interval_start: float, time_interval_end: float
) -> Dict:
    """Joins data from listchannels and fwdinghistory to have extended
    information about channels.

    :return: dict of channel information with channel_id as keys
    """
    forwarding_analyzer = ForwardingAnalyzer(node)
    forwarding_analyzer.initialize_forwarding_stats(
        time_interval_start, time_interval_end
    )

    # dict with channel_id keys
    statistics = forwarding_analyzer.get_forwarding_statistics_channels()
    logger.debug(
        f"Time interval (between first and last forwarding) is "
        f"{forwarding_analyzer.max_time_interval_days:6.2f} days."
    )
    # join the two data sets:
    channels = node.get_unbalanced_channels(unbalancedness_greater_than=0.0)

    for k, c in channels.items():
        # we may not have forwarding data for every channel
        chan_stats = statistics.get(c["chan_id"], {})
        c["forwardings_per_channel_age"] = (
            chan_stats.get("number_forwardings", 0.01) / c["age"]
        )
        c["bandwidth_demand"] = (
            max(
                nan_to_zero(chan_stats.get("mean_forwarding_in", 0)),
                nan_to_zero(chan_stats.get("mean_forwarding_out", 0)),
            )
            / c["capacity"]
        )
        c["fees_total"] = chan_stats.get("fees_total", 0)
        try:
            c["fees_total_per_week"] = chan_stats.get("fees_total", 0) / (
                forwarding_analyzer.max_time_interval_days / 7
            )
        except ZeroDivisionError:
            c["fees_total_per_week"] = float("nan")
        c["flow_direction"] = chan_stats.get("flow_direction", float("nan"))
        c["median_forwarding_in"] = chan_stats.get("median_forwarding_in", float("nan"))
        c["median_forwarding_out"] = chan_stats.get(
            "median_forwarding_out", float("nan")
        )
        c["mean_forwarding_in"] = chan_stats.get("mean_forwarding_in", float("nan"))
        c["mean_forwarding_out"] = chan_stats.get("mean_forwarding_out", float("nan"))
        c["number_forwardings"] = chan_stats.get("number_forwardings", 0)
        c["largest_forwarding_amount_in"] = chan_stats.get(
            "largest_forwarding_amount_in", float("nan")
        )
        c["largest_forwarding_amount_out"] = chan_stats.get(
            "largest_forwarding_amount_out", float("nan")
        )
        c["total_forwarding_in"] = chan_stats.get("total_forwarding_in", 0)
        c["total_forwarding_out"] = chan_stats.get("total_forwarding_out", 0)

        # action required if flow same direction as unbalancedness
        # or bandwidth demand too high
        # TODO: refine 'action_required' by better metric
        if (
            c["unbalancedness"] * c["flow_direction"] > 0
            and abs(c["unbalancedness"]) > settings.UNBALANCED_CHANNEL
        ):
            c["action_required"] = True
        else:
            c["action_required"] = False
        if c["bandwidth_demand"] > 0.5:
            c["action_required"] = True

    return channels
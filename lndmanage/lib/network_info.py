from collections import defaultdict
from statistics import median, mean

import numpy as np
import networkx as nx

from lndmanage.lib.ln_utilities import convert_channel_id_to_short_channel_id
from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class NetworkAnalysis(object):
    """
    Class for network analysis.

    """

    def __init__(self, node):
        """
        :param node: :class:`lib.node.LndNode`
        """

        self.node = node
        self.nodes_info = None

    def find_nodes_with_largest_degrees(self, node_count=10):
        """
        Finds node_count nodes in the graph, which have the most connections.

        :param node_count: int
        :return: list of nodes sorted by degree
        """

        nodes_and_degrees = list(self.node.network.graph.degree)

        # number of channels in networkx is twice the real number of channels
        nodes_and_degrees = [(n[0], n[1] // 2) for n in nodes_and_degrees]

        nodes_sorted_by_degrees_decremental = sorted(
            nodes_and_degrees, key=lambda x: x[1], reverse=True)

        return nodes_sorted_by_degrees_decremental[:node_count]

    def find_nodes_with_highest_total_capacities(self, node_count=10):
        """
        Finds node_count nodes in the graph with the largest amount of bitcoin
        assigned in their channels.

        :param node_count: int
        :return: list of nodes sorted by capacity
        """

        nodes_and_capacity = []

        for n in self.node.network.graph.nodes:
            total_capacity = 0
            edges = self.node.network.graph.edges(n, data=True)
            for e in edges:
                total_capacity += e[2]['capacity']
            nodes_and_capacity.append((n, total_capacity))

        nodes_and_capacity = sorted(
            nodes_and_capacity, key=lambda x: x[1], reverse=True)

        return nodes_and_capacity[:node_count]

    def get_sorted_nodes_by_property(self, key='capacity', node_count=10,
                                     decrementing=True, min_degree=0):
        """
        Returns sorted list of nodes by the key field.

        A minimal number of degree of the target nodes can be given.

        :param key: property by which it is sorted
        :param node_count:
        :param decrementing:
        :param min_degree:
        :return: sorted list
        """

        nodes = []
        for node_info in self.nodes_info:
            if node_info['degree'] >= min_degree:
                nodes.append(node_info)

        sorted_nodes = sorted(
            nodes, key=lambda x: x[key], reverse=decrementing)

        return sorted_nodes[:node_count]

    def node_info_basic(self, node_pub_key):
        node_info = self.node.get_node_info(node_pub_key)
        # calculate average and mean channel fees

        base_fees = []
        fee_rates_milli_msat = []
        capacities = []
        for c in node_info['channels']:
            # Determine which policy to look at.
            if node_pub_key == c.node1_pub:
                policy = c.node1_policy
            else:
                policy = c.node2_policy
            base_fees.append(policy.fee_base_msat)
            fee_rates_milli_msat.append(policy.fee_rate_milli_msat)
            capacities.append(c.capacity)

        node_info['mean_base_fee'] = int(mean(base_fees))
        node_info['median_base_fee'] = int(median(base_fees))
        node_info['mean_fee_rate'] = round(mean(fee_rates_milli_msat) / 1E6, 6)
        node_info['median_fee_rate'] = round(median(fee_rates_milli_msat) / 1E6, 6)
        node_info['mean_capacity'] = int(mean(capacities))
        node_info['median_capacity'] = int(median(capacities))

        return node_info

    def node_information(self, node_pub_key):
        """
        Extracts information on a node from the networkx graph.

        :param node_pub_key: string, public key of the analyzed node
        :return: dict of properties
        """

        total_capacity = 0
        edges = self.node.network.graph.edges(node_pub_key, data=True)
        degree = len(edges)
        for e in edges:
            total_capacity += e[2]['capacity']

        return {'node_id': node_pub_key,
                'capacity': total_capacity,
                'degree': degree,
                'capacity_per_channel': total_capacity / max(1, degree),
                'user_nodes': self.number_of_connected_user_nodes(
                    node_pub_key),
                }

    def nodes_information(self):
        """
        Extract all nodes' properties from the network.

        :return: list of dicts of nodes
        """
        nodes = []
        for n in self.node.network.graph.nodes:
            node_info = self.node_information(n)
            nodes.append(node_info)
        return nodes

    def print_node_overview(self, node_pub_key):
        """
        Prints an overview of any node on the network.

        Lists the channels and their capacities/fees.

        :param node_pub_key:
        """

        logger.info("-------- Node overview for node {} --------".format(
            node_pub_key))
        edges = list(self.node.network.graph.edges(node_pub_key, data=True))
        sorted(edges, key=lambda x: x[1])
        logger.info("Node has {} channels".format(len(edges)))
        for ie, e in enumerate(edges):
            logger.info("Channel number: {} between {} and {}".format(
                ie, e[0], e[1]))
            logger.info("Channel information: {}".format(e[2]))

    def number_of_connected_user_nodes(self, node_pub_key):
        """
        Determines the number of 'user' nodes that a node is connected to.

        A user node is determined by having a smaller amount of degrees than
        a certain value NUMBER_CHANNELS_DEFINING_USER_NODE. A node with a
        low number of connections is assumed to be a user node.

        :param node_pub_key: public_key of a node to be analyzed
        :return:
        """

        connected_end_nodes = 0
        edges = self.node.network.graph.edges(node_pub_key)

        for e in edges:
            degree_neighbor = self.node.network.graph.degree(e[1]) // 2
            if degree_neighbor <= settings.NUMBER_CHANNELS_DEFINING_USER_NODE:
                connected_end_nodes += 1

        return connected_end_nodes

    def get_nodes_n_hops_away(self, node_pub_key, n):
        """
        Returns all nodes, which are n hops away from a given
        node_pub_key node.

        :param node_pub_key: string
        :param n: int
        :return: dict with nodes and distance as value
        """

        return nx.single_source_shortest_path_length(
            self.node.network.graph, node_pub_key, cutoff=n)

    def secondary_hops_added(self, node_pub_key):
        """
        Determines the number of secondary hops added if connected to the node.

        :param node_pub_key: str
        :return: int
        """
        potential_new_second_neighbors = set(
            nx.all_neighbors(self.node.network.graph, node_pub_key))
        current_close_neighbors = set(
            self.get_nodes_n_hops_away(self.node.pub_key, 2).keys())
        new_second_neighbors = potential_new_second_neighbors.difference(
            current_close_neighbors)
        return len(new_second_neighbors)

    def nodes_most_second_neighbors(self, node_pub_key, number_of_nodes=10):
        """
        Which node should be added in order to reach the most other nodes
        with two hops?

        :param node_pub_key: string
        :param number_of_nodes: int
        :return: list of results nodes, adding the most secondary neighbors
        """

        node_candidates = []

        # set of nodes currently two hops away
        current_close_neighbors = set(
            self.get_nodes_n_hops_away(node_pub_key, 2).keys())

        # loop through nodes in the network and check their direct neighbors
        for n in self.node.network.graph:
            potential_new_second_neighbors = set(
                nx.all_neighbors(self.node.network.graph, n))

            # subtract current_close_neighbors from
            # the potential new second neighbors
            new_second_neighbors = potential_new_second_neighbors.difference(
                current_close_neighbors)

            # add the node and its number of secondary neighbors to a list
            node_candidates.append([n, len(new_second_neighbors)])

        nodes_sorted = sorted(
            node_candidates, key=lambda x: x[1], reverse=True)

        return nodes_sorted[:number_of_nodes]

    def print_find_nodes_giving_most_secondary_hops(self, node_pub_key):
        """
        Determines and prints the nodes giving the most second
        nearest neighbors.

        :param node_pub_key: node public key of the interested node
        """

        nodes = self.nodes_most_second_neighbors(node_pub_key)
        logger.info("Finding all nodes, which when connected would give n new "
                    "nodes reachable with two hops.")

        for node, number_neighbors in nodes:
            logger.info(f"Node: {node} - new neighbors: {number_neighbors}")

    def determine_channel_openings(self, from_days_ago):
        """
        Determines all channel openings in the last `from_days_ago` days and
        creates a dictionary of nodes involved.

        The dictionary values contain tuples of channel creation height and
        capacity of the channels that were opened.

        :param from_days_ago: int
        :return: dict, keys: node public keys, values: (block height, capacity)
        """

        logger.info(f"Determining channel openings in the last "
                    f"{from_days_ago} days (excluding already closed ones).")
        # retrieve all channels in the network
        all_channels_list = self.node.network.edges.keys()

        # make sure the channels are sorted by age, oldest first
        all_channels_list = sorted(all_channels_list)

        # determine blockheight from where to start the analysis
        # we have about six blocks per hour
        blockheight_start = self.node.blockheight - from_days_ago * 24 * 6

        # take only youngest channels
        channels_filtered_and_creation_time = []
        for cid in all_channels_list:
            height = convert_channel_id_to_short_channel_id(cid)[0]
            if height > blockheight_start:
                channels_filtered_and_creation_time.append((cid, height))
        logger.info(f"In the last {from_days_ago} days, there were at least "
                    f"{len(channels_filtered_and_creation_time)} "
                    f"channel openings.")

        # analyze the openings and assign tuples of
        # (creation height, channel capacity) to nodes
        channel_openings_per_node_dict = defaultdict(list)
        for c, height in channels_filtered_and_creation_time:
            edge = self.node.network.edges[c]
            channel_openings_per_node_dict[edge['node1_pub']].append(
                (height, edge['capacity']))
            channel_openings_per_node_dict[edge['node2_pub']].append(
                (height, edge['capacity']))

        return channel_openings_per_node_dict

    def calculate_channel_opening_statistics(self, from_days_ago,
                                             exclude_openings_less_than=5):
        """
        Calculates basic channel opening statistics for each node.

        :param from_days_ago: int
        :param exclude_openings_less_than: int, nodes with smaller channel
            openings than this are excluded
        :return: dict, keys: nodes, values: serveral heuristics
        """

        openings_per_node_dict = self.determine_channel_openings(from_days_ago)
        opening_statistics_per_node = {}

        for n, nv in openings_per_node_dict.items():
            # convert opening characteristics (heights and capacities) to lists
            heights = [opening[0] for opening in nv]
            capacities = [opening[1] for opening in nv]

            # calculate the blockheight differences between successive
            # channel openings (tells about frequency)
            delta_heights = np.diff(heights)

            # calculate median and average differences of channel openings
            # (median can give hints on bursts of openings)
            median_opening_time = np.median(delta_heights)
            average_opening_time = np.mean(delta_heights)

            # other interesting quantities
            openings = len(capacities)
            openings_total_capacity = sum(capacities)
            openings_average_capacity = \
                float(openings_total_capacity) / openings
            node_total_capacity = self.node.network.node_capacity(n)
            node_number_channels = self.node.network.number_channels(n)

            # put all the data in a dictionary, which can then be handled
            # by the node recommendation class
            if openings > exclude_openings_less_than:
                opening_statistics_per_node[n] = {
                    'opening_median_time': median_opening_time,
                    'opening_average_time': average_opening_time,
                    'openings_average_capacity':  # unit: btc
                        openings_average_capacity / 1E8,
                    'openings': openings,
                    'openings_total_capacity':  # unit: btc
                        openings_total_capacity / 1E8,
                    'relative_openings':
                        float(openings) / node_number_channels,
                    'relative_total_capacity':  # unit: ksat
                        0 if node_total_capacity == 0 else float(openings_total_capacity) / node_total_capacity,
                }

        return opening_statistics_per_node

    def distance(self, first_node, second_node):
        """
        Calculates the distance in hops from first node to second node.
        :param first_node: str
        :param second_node: str
        :return: int
        """
        try:
            distance = nx.shortest_path_length(
                self.node.network.graph, source=first_node, target=second_node)
        except nx.exception.NetworkXNoPath:
            distance = float('inf')  # some high number

        return distance


if __name__ == '__main__':
    from lndmanage.lib.node import LndNode

    import logging.config
    logging.config.dictConfig(settings.logger_config)

    nd = LndNode()
    network_analysis = NetworkAnalysis(nd)

    nodes_capacities = network_analysis.find_nodes_with_highest_total_capacities()
    network_analysis.print_find_nodes_giving_most_secondary_hops(nd.pub_key)

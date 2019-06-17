import networkx as nx

import _settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class NetworkAnalysis(object):
    """
    Class for network analysis.

    :param node: :class:`lib.node.LndNode`
    """

    def __init__(self, node):
        self.node = node
        self.nodes_info = self.nodes_information()

    def find_nodes_with_largest_degrees(self, node_count=10):
        """
        Finds node_count nodes in the graph, which have the most connections.

        :param node_count: int
        :return: list of nodes sorted by degree
        """

        nodes_and_degrees = list(self.node.network.graph.degree)

        # number of channels in networkx is twice the real number of channels
        nodes_and_degrees = [(n[0], n[1] // 2) for n in nodes_and_degrees]

        nodes_sorted_by_degrees_decremental = sorted(nodes_and_degrees, key=lambda x: x[1], reverse=True)
        return nodes_sorted_by_degrees_decremental[:node_count]

    def find_nodes_with_highest_total_capacities(self, node_count=10):
        """
        Finds node_count nodes in the graph with the largest amount of bitcoin assigned in their channels.

        :param node_count: int
        :return: list of nodes sorted by cacpacity
        """

        nodes_and_capacity = []
        for n in self.node.network.graph.nodes:
            total_capacity = 0
            edges = self.node.network.graph.edges(n, data=True)
            for e in edges:
                total_capacity += e[2]['capacity']
            nodes_and_capacity.append((n, total_capacity))
        nodes_and_capacity = sorted(nodes_and_capacity, key=lambda x: x[1], reverse=True)
        return nodes_and_capacity[:node_count]

    def get_sorted_nodes_by_property(self, key='capacity', node_count=10, decrementing=True, min_degree=0):
        """
        Returns sorted list of nodes by the key field. A minimal number of degree of the target nodes can be given.

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
        sorted_nodes = sorted(nodes, key=lambda x: x[key], reverse=decrementing)
        return sorted_nodes[:node_count]

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
                'user_nodes': self.number_of_connected_user_nodes(node_pub_key),
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
        Prints an overview of any node on the network. Lists the channels and their capacities/fees.

        :param node_pub_key:
        """

        logger.info("-------- Node overview for node {} --------".format(node_pub_key))
        edges = list(self.node.network.graph.edges(node_pub_key, data=True))
        sorted(edges, key=lambda x: x[1])
        logger.info("Node has {} channels".format(len(edges)))
        for ie, e in enumerate(edges):
            logger.info("Channel number: {} between {} and {}".format(ie, e[0], e[1]))
            logger.info("Channel information: {}".format(e[2]))

    def number_of_connected_user_nodes(self, node_pub_key):
        """
        Determines the number of 'user' nodes that a node is connected to. A user node is determined by having a
        smaller amount of degrees than a certain value NUMBER_CHANNELS_DEFINING_USER_NODE. A node with a low number of
        connections is assumed to be a user node.

        :param node_pub_key: public_key of a node to be analyzed
        :return:
        """

        connected_end_nodes = 0
        edges = self.node.network.graph.edges(node_pub_key)
        for e in edges:
            degree_neighbor = self.node.network.graph.degree(e[1]) // 2
            if degree_neighbor <= _settings.NUMBER_CHANNELS_DEFINING_USER_NODE:
                connected_end_nodes += 1
        return connected_end_nodes

    def get_nodes_n_hops_away(self, node_pub_key, n):
        """
        Returns all nodes, which are n hops away from a given node_pub_key node.

        :param node_pub_key: string
        :param n: int
        :return: dict with nodes and distance as value
        """

        return nx.single_source_shortest_path_length(self.node.network.graph, node_pub_key, cutoff=n)

    def secondary_hops_added(self, node_pub_key):
        """
        Determines the number of secondary hops added if connected to the node.
        :param node_pub_key: str
        :return: int
        """
        potential_new_second_neighbors = set(nx.all_neighbors(self.node.network.graph, node_pub_key))
        # print('pot new', potential_new_second_neighbors)
        current_close_neighbors = set(self.get_nodes_n_hops_away(self.node.pub_key, 2).keys())
        # print('curr close', current_close_neighbors)
        new_second_neighbors = potential_new_second_neighbors.difference(current_close_neighbors)
        # print('new sec', new_second_neighbors)
        # print(len(new_second_neighbors))
        return len(new_second_neighbors)

    def find_nodes_giving_most_secondary_hops(self, node_pub_key, results=10):
        """
        Which node should be added in order to reach the most other nodes with two hops?

        :param node_pub_key: string
        :param results: int
        :return: list of results nodes, which bring the most secondary neighbors
        """

        node_candidates = []

        # these are the neighbors currently two hops away
        current_close_neighbors = set(self.get_nodes_n_hops_away(node_pub_key, 2).keys())

        for n in self.node.network.graph:
            # find neighbors of all nodes in the graph
            potential_new_second_neighbors = set(nx.all_neighbors(self.node.network.graph, n))
            # subtract current_close_neighbors from the potential new second neighbors
            new_second_neighbors = potential_new_second_neighbors.difference(current_close_neighbors)
            # add the node and its number of secondary neighbors to a list
            node_candidates.append([n, len(new_second_neighbors)])
        return sorted(node_candidates, key=lambda x: x[1], reverse=True)[:results]

    def print_find_nodes_giving_most_secondary_hops(self, node_pub_key):
        """
        Determines and prints the nodes giving the most second nearest neighbors.

        :param node_pub_key: node public key of the interested node
        """

        nodes = self.find_nodes_giving_most_secondary_hops(node_pub_key)
        logger.info("Finding all nodes, which when connected would give n new nodes reachable with two hops.")
        for node, number_neighbors in nodes:
            logger.info(f"Node: {node} - new neighbors: {number_neighbors}")

    def distance(self, first_node, second_node):
        """
        Calculates the distance in hops from first node to second node.
        :param first_node: str
        :param second_node: str
        :return: int
        """
        return nx.shortest_path_length(self.node.network.graph, source=first_node, target=second_node)


if __name__ == '__main__':
    from lib.node import LndNode

    import logging.config
    logging.config.dictConfig(_settings.logger_config)

    nd = LndNode()
    network_analysis = NetworkAnalysis(nd)

    nodes_capacities = network_analysis.find_nodes_with_highest_total_capacities()
    network_analysis.print_find_nodes_giving_most_secondary_hops(nd.pub_key)

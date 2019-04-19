import _settings
import os
import time
import pickle

import networkx as nx

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Network(object):
    """
    Contains the network graph. The graph is received from the LND API or from a cached file,
    which contains the graph younger than `settings.CACHING_RETENTION_MINUTES`.

    :param node: :class:`lib.node.LndNode` object
    """

    def __init__(self, node):
        logger.info("Initializing network graph.")
        self.node = node
        self.edges = {}
        self.graph = nx.MultiDiGraph()
        self.cached_reading_graph_edges()

    def cached_reading_graph_edges(self):
        """
        Checks if networkx and edges dictionary pickles are present. If they are older than
        CACHING_RETENTION_MINUTES, make fresh pickles, else read them from the files.
        """
        dir = os.path.dirname(__file__)
        cache_edges_filename = os.path.join(dir, '..', 'cache', 'graph.gpickle')
        cache_graph_filename = os.path.join(dir, '..', 'cache', 'edges.gpickle')

        try:
            timestamp_graph = os.path.getmtime(cache_graph_filename)
        except FileNotFoundError:
            timestamp_graph = 0  # set very old timestamp

        if timestamp_graph < time.time() - _settings.CACHING_RETENTION_MINUTES * 60:  # old graph in file
            logger.info(f"Saved graph is too old. Fetching new one.")
            self.set_graph_and_edges()
            nx.write_gpickle(self.graph, cache_graph_filename)
            with open(cache_edges_filename, 'wb') as file:
                pickle.dump(self.edges, file)
        else:  # recent graph in file
            logger.info("Reading graph from file.")
            self.graph = nx.read_gpickle(cache_graph_filename)
            with open(cache_edges_filename, 'rb') as file:
                self.edges = pickle.load(file)

    def set_graph_and_edges(self):
        """
        Reads in the networkx graph and edges dictionary.
        :return: nx graph and edges dict
        """
        raw_graph = self.node.get_raw_network_graph()

        for n in raw_graph.nodes:
            self.graph.add_node(
                n.pub_key,
                alias=n.alias,
                last_update=n.last_update,
                # addresses=n.addresses,  # incompatible with pickling
                color=n.color)

        for e in raw_graph.edges:
            # TODO refactor out grpc file format
            # create a dictionary for channel_id lookups
            self.edges[e.channel_id] = {
                'node1_pub': e.node1_pub,
                'node2_pub': e.node2_pub,
                'capacity': e.capacity,
                'last_update': e.last_update,
                'channel_id': e.channel_id,
                'node1_policy': {
                    'time_lock_delta': e.node1_policy.time_lock_delta,
                    'fee_base_msat': e.node1_policy.fee_base_msat,
                    'fee_rate_milli_msat': e.node1_policy.fee_rate_milli_msat,
                    'disabled': e.node1_policy.disabled
                },
                'node2_policy': {
                    'time_lock_delta': e.node2_policy.time_lock_delta,
                    'fee_base_msat': e.node2_policy.fee_base_msat,
                    'fee_rate_milli_msat': e.node2_policy.fee_rate_milli_msat,
                    'disabled': e.node2_policy.disabled
                }}

            # add vertices to network graph for edge-based lookups
            self.graph.add_edge(
                e.node2_pub,
                e.node1_pub,
                channel_id=e.channel_id,
                last_update=e.last_update,
                capacity=e.capacity,
                fees={
                    'time_lock_delta': e.node2_policy.time_lock_delta,
                    'fee_base_msat': e.node2_policy.fee_base_msat,
                    'fee_rate_milli_msat': e.node2_policy.fee_rate_milli_msat,
                    'disabled': e.node2_policy.disabled
                })
            self.graph.add_edge(
                e.node1_pub,
                e.node2_pub,
                channel_id=e.channel_id,
                last_update=e.last_update,
                capacity=e.capacity,
                fees={
                    'time_lock_delta': e.node1_policy.time_lock_delta,
                    'fee_base_msat': e.node1_policy.fee_base_msat,
                    'fee_rate_milli_msat': e.node1_policy.fee_rate_milli_msat,
                    'disabled': e.node1_policy.disabled
                })

    def get_node_alias(self, node_pub_key):
        """
        Wrapper to get the alias of a node given its public key.
        :param node_pub_key:
        :return: alias string
        """
        return self.graph.node[node_pub_key]['alias']


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(_settings.logger_config)

    from lib.node import LndNode
    nd = LndNode()
    print(f"Graph size: {nd.network.graph.size()}")
    print(f"Number of channels: {len(nd.network.edges.keys())}")

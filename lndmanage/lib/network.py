import os
import time
import pickle
from typing import Dict, TYPE_CHECKING

import networkx as nx

from lndmanage.lib.data_types import NodePair
from lndmanage.lib.utilities import profiled
from lndmanage.lib.ln_utilities import convert_channel_id_to_short_channel_id
from lndmanage.lib.liquidityhints import LiquidityHintMgr
from lndmanage.lib.rating import ChannelRater
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def make_cache_filename(filename: str):
    """Creates the cache directory and gives back the absolute path to it for filename."""
    cache_dir = os.path.join(settings.home_dir, 'cache')
    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)
    return os.path.join(cache_dir, filename)


class Network:
    """
    Contains the network graph.

    The graph is received from the LND API or from a cached file,
    which contains the graph younger than `settings.CACHING_RETENTION_MINUTES`.
    """
    node: 'LndNode'
    edges: Dict
    graph: nx.MultiGraph
    liquidity_hints: LiquidityHintMgr
    max_pair_capacity: Dict[NodePair, int]

    def __init__(self, node: 'LndNode'):
        self.node = node
        self.load_graph()
        self.load_liquidity_hints()
        self.channel_rater = ChannelRater(self)

    @profiled
    def load_graph(self):
        """
        Checks if networkx and edges dictionary pickles are present. If they are older than
        CACHING_RETENTION_MINUTES, make fresh pickles, else read them from the files.
        """
        cache_edges_filename = make_cache_filename('graph.gpickle')
        cache_graph_filename = make_cache_filename('edges.gpickle')

        try:
            timestamp_graph = os.path.getmtime(cache_graph_filename)
        except FileNotFoundError:
            timestamp_graph = 0  # set very old timestamp

        if timestamp_graph < time.time() - settings.CACHING_RETENTION_MINUTES * 60:  # old graph in file
            logger.info(f"> Cached graph is too old. Fetching new one.")
            self.set_graph_edges_pairs()
            with open(cache_graph_filename, 'wb') as file:
                pickle.dump(self.graph, file, pickle.HIGHEST_PROTOCOL)
            with open(cache_edges_filename, 'wb') as file:
                pickle.dump(self.edges, file)
        else:  # recent graph in file
            with open(cache_graph_filename, 'rb') as file:
                self.graph = pickle.load(file)
            with open(cache_edges_filename, 'rb') as file:
                self.edges = pickle.load(file)
            logger.info(f"> Loaded graph from file: {len(self.graph)} nodes, {len(self.edges)} channels.")

        self.set_max_pair_capacities()

    @profiled
    def load_liquidity_hints(self):
        cache_hints_filename = make_cache_filename('liquidity_hints.gpickle')
        try:
            with open(cache_hints_filename, 'rb') as file:
                self.liquidity_hints = pickle.load(file)
                num_badness_hints = len([f for f in self.liquidity_hints._badness_hints.values() if f])
            logger.info(f"> Loaded liquidity hints: {len(self.liquidity_hints._liquidity_hints)} hints, {num_badness_hints} badness hints.")
        except FileNotFoundError:
            self.liquidity_hints = LiquidityHintMgr(self.node.pub_key)
        except Exception as e:
            logger.exception(e)

        # we extend our information with data from mission control
        if self.liquidity_hints.mc_sync_timestamp < time.time() - settings.CACHING_RETENTION_MINUTES * 60:
            mc_pairs = self.node.query_mc()
            self.liquidity_hints.extend_with_mission_control(mc_pairs)
            logger.info(f"> Synced mission control data (imported {len(mc_pairs)} pairs).")
            self.save_liquidty_hints()

    @profiled
    def save_liquidty_hints(self):
        cache_hints_filename = make_cache_filename('liquidity_hints.gpickle')
        with open(cache_hints_filename, 'wb') as file:
            pickle.dump(self.liquidity_hints, file)

    @profiled
    def set_graph_edges_pairs(self):
        """
        Reads in the networkx graph and edges dictionary.

        :return: nx graph and edges dict
        """
        self.edges = {}
        self.graph = nx.MultiGraph()
        raw_graph = self.node.get_raw_network_graph()

        for n in raw_graph.nodes:
            if n.addresses:
                # TODO: handle also ipv6 and onion addresses
                address = n.addresses[0].addr
                if 'onion' in address or '[' in address:
                    address = ''
            else:
                address = ''

            self.graph.add_node(
                n.pub_key,
                alias=n.alias.encode("ascii", "ignore").decode(),  # we remove non-ascii chars
                last_update=n.last_update,
                address=address,
                color=n.color)

        for e in raw_graph.edges:
            node_pair = NodePair((e.node1_pub, e.node2_pub))

            policy1 = {
                'time_lock_delta': e.node1_policy.time_lock_delta,
                'fee_base_msat': e.node1_policy.fee_base_msat,
                'fee_rate_milli_msat': e.node1_policy.fee_rate_milli_msat,
                'last_update': e.node1_policy.last_update,
                'disabled': e.node1_policy.disabled,
                'min_htlc': e.node1_policy.min_htlc,
                'max_htlc_msat': e.node1_policy.max_htlc_msat
            }
            policy2 = {
                'time_lock_delta': e.node2_policy.time_lock_delta,
                'fee_base_msat': e.node2_policy.fee_base_msat,
                'fee_rate_milli_msat': e.node2_policy.fee_rate_milli_msat,
                'last_update': e.node2_policy.last_update,
                'disabled': e.node2_policy.disabled,
                'min_htlc': e.node2_policy.min_htlc,
                'max_htlc_msat': e.node2_policy.max_htlc_msat
            }
            # create a dictionary for channel_id lookups
            self.edges[e.channel_id] = {
                'node1_pub': e.node1_pub,
                'node2_pub': e.node2_pub,
                'node_pair': node_pair,
                'capacity': e.capacity,
                'last_update': e.last_update,
                'channel_id': e.channel_id,
                'chan_point': e.chan_point,
                'policies': {
                    e.node1_pub > e.node2_pub: policy1,
                    e.node2_pub > e.node1_pub: policy2
                }
            }

            # add vertices to network graph for edge-based lookups
            self.graph.add_edge(
                e.node1_pub,
                e.node2_pub,
                node_pair=node_pair,
                channel_id=e.channel_id,
                last_update=e.last_update,
                capacity=e.capacity,
                fees={
                    e.node1_pub > e.node2_pub: policy1,
                    e.node2_pub > e.node1_pub: policy2,
                })

    def set_max_pair_capacities(self):
        self.max_pair_capacity = {}
        for cid, e in self.edges.items():
            node_pair = NodePair((e['node1_pub'], e['node2_pub']))
            # determine the maximal capacity over a key pair
            if not self.max_pair_capacity.get(node_pair):
                self.max_pair_capacity[node_pair] = e['capacity']
            else:
                if self.max_pair_capacity[node_pair] < e['capacity']:
                    self.max_pair_capacity[node_pair] = e['capacity']

    def number_channels(self, node_pub_key):
        """
        Determines the degree of a given node.

        :param node_pub_key: str
        :return: int
        """
        try:
            number_of_channels = self.graph.degree[node_pub_key] / 2
        except KeyError:
            number_of_channels = 0
        return number_of_channels

    def node_capacity(self, node_pub_key):
        """
        Calculates the total capacity of a node in satoshi.

        :param node_pub_key: str
        :return: int
        """
        total_capacity = 0
        edges = self.graph.edges(node_pub_key, data=True)
        for e in edges:
            total_capacity += e[2]['capacity']
        return total_capacity

    def node_alias(self, node_pub_key):
        """
        Wrapper to get the alias of a node given its public key.

        :param node_pub_key:
        :return: alias string
        """
        try:
            return self.graph.nodes[node_pub_key]['alias']
        except KeyError:
            return 'unknown alias'

    def node_address(self, node_pub_key):
        """
        Returns the IP/onion addresses of a node.

        :param node_pub_key:
        :return: list
        """
        return self.graph.nodes[node_pub_key]['address']

    def node_age(self, node_pub_key):
        """
        Determine the approximate node's age by its oldest channel.

        :param node_pub_key: str
        :return: float, days
        """

        # find all channels of nodes
        node_edges = self.graph.edges(node_pub_key, data=True)

        # collect all channel's ages in terms of blockheights
        channel_ages = []
        for e in node_edges:
            channel_id = e[2]['channel_id']
            height, index, output = convert_channel_id_to_short_channel_id(channel_id)
            channel_age = self.node.blockheight - height
            channel_ages.append(channel_age)

        # determine oldest channel's age
        node_age = max(channel_ages)

        # convert to days from actual blockheight
        node_age_days = float(node_age) * 10 / (60 * 24)
        return node_age_days

    def neighbors(self, node_pub_key):
        """
        Finds all the node pub keys of nearest neighbor nodes.

        :param node_pub_key:  str
        :return: node_pub_key: str
        """
        neighbors = nx.neighbors(self.graph, node_pub_key)
        for n in neighbors:
            yield n

    def second_neighbors(self, node_pub_key):
        """
        Finds all the node pub keys of second nearest neighbor nodes (multiple appearances allowed).

        :param node_pub_key: str
        :return: node_pub_key: str
        """
        for neighbor_list in [self.graph.neighbors(n) for n in self.graph.neighbors(node_pub_key)]:
            for n in neighbor_list:
                yield n

    def nodes_in_neighborhood_of_nodes(self, nodes, blacklist_nodes, nnodes=100):
        """
        Takes a list of nodes and finds the neighbors with most connections to the nodes.

        :param nodes: list
        :param blacklist_nodes: list of node_pub_keys to be excluded from counting
        :param nnodes: int, limit for the number of nodes returned
        :return: list of tuples, (str pub_key, int number of neighbors)
        """
        nodes = set(nodes)
        # eliminate blacklisted nodes
        nodes = nodes.difference(blacklist_nodes)
        neighboring_nodes = []
        for general_node in self.graph.nodes:
            neighbors_general_node = set(self.neighbors(general_node))
            intersection_with_nodes = nodes.intersection(neighbors_general_node)
            number_of_connection_with_nodes = len(intersection_with_nodes)
            neighboring_nodes.append((general_node, number_of_connection_with_nodes))

        sorted_neighboring_nodes = sorted(neighboring_nodes, key=lambda x: x[1], reverse=True)
        return sorted_neighboring_nodes[:nnodes]


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(settings.logger_config)

    from lndmanage.lib.node import LndNode
    nd = LndNode('')
    print(f"Graph size: {nd.network.graph.size()}")
    print(f"Number of channels: {len(nd.network.edges.keys())}")

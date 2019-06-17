import time
import re
from collections import OrderedDict
import urllib.request
from urllib.error import HTTPError

import _settings

from lib.forwardings import ForwardingAnalyzer
from lib.network_info import NetworkAnalysis

import logging.config
logging.config.dictConfig(_settings.logger_config)
logger = logging.getLogger(__name__)

# define printing shortcuts, alignments, and cutoffs
print_node_format = {
    'alias': {
        'dict_key': 'alias',
        'description': 'alias',
        'width': 20,
        'format': '<30.29',
        'align': '^',
    },
    'con': {
        'dict_key': 'connections',
        'description': 'connections with nodes in list',
        'width': 6,
        'format': '6.0f',
        'align': '>',
    },
    'cpc': {
        'dict_key': 'capacity_per_channel',
        'description': 'capacity per channel [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'dist': {
        'dict_key': 'distance',
        'description': 'distance [hops]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'flow': {
        'dict_key': 'flow_direction',
        'description': 'flow_direction',
        'width': 6,
        'format': '6.2f',
        'align': '>',
    },
    'nchan': {
        'dict_key': 'number_channels',
        'description': 'number of channels',
        'width': 6,
        'format': '6.0f',
        'align': '>',
    },
    'rpk': {
        'dict_key': 'remote_pubkey',
        'description': 'remote public key',
        'width': 66,
        'format': '<66',
        'align': '^',
    },
    'cap': {
        'dict_key': 'total_capacity',
        'description': 'total capacity [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'tot': {
        'dict_key': 'total_forwarding',
        'description': 'total forwarded [sat]',
        'width': 9,
        'format': '9d',
        'align': '>',
    },
}


class RecommendNodes(object):
    """
    A class to recommend nodes to connect to.
    """
    def __init__(self, node, show_connected=False, show_addresses=False):
        self.node = node
        self.network_analysis = NetworkAnalysis(self.node)

        self.show_connected = show_connected
        self.show_address = show_addresses

    def good_old(self):
        """
        Gives back a list of nodes to which we already had a good relationship with historic forwardings.
        :return: dict, nodes sorted by total amount forwarded
        """
        forwarding_analyzer = ForwardingAnalyzer(self.node)
        forwarding_analyzer.initialize_forwarding_data(0, time.time())  # analyze all historic forwardings
        nodes = forwarding_analyzer.get_forwarding_statistics_nodes()
        if not self.show_connected:
            nodes = self.exclude_connected_nodes(nodes)
        nodes = self.add_metadata_and_remove_pruned(nodes)
        return nodes

    def flow_analysis(self, out_direction=True, last_forwardings_to_analyze=200):
        """
        Does a flow analysis and suggests nodes which have demand for inbound liquidity.
        :param out_direction: bool, if True outward flowing nodes are displayed
        :param last_forwardings_to_analyze: int, number of forwardings in analysis
        :return: nodes dict with metadata
        """
        forwarding_analyzer = ForwardingAnalyzer(self.node)
        forwarding_analyzer.initialize_forwarding_data(0, time.time())  # analyze all historic forwardings
        nodes_in, nodes_out = forwarding_analyzer.simple_flow_analysis(last_forwardings_to_analyze)
        raw_nodes = nodes_out if out_direction else nodes_in
        if not self.show_connected:
            raw_nodes = self.exclude_connected_nodes(raw_nodes)
        nodes = self.add_metadata_and_remove_pruned(raw_nodes)
        return nodes

    def nodefile(self, source, distributing_nodes=False, exclude_hubs=True):
        """
        Parses a file/url (source) for node public keys and displays additional info.
        If distributing_nodes is set to True, nodes which are well connected to the nodes in the nodefile are displayed.
        Big hubs can be excluded by exclude_hubs.
        :param source: str
        :param distributing_nodes: bool
        :param exclude_hubs: bool
        """
        source_found = False
        text = None

        # try first to find a web source behind source
        try:
            response = urllib.request.urlopen(source)
            data = response.read()
            text = data.decode('utf-8')
            logger.info("Found a web source for the node list.")
            source_found = True

        except HTTPError as e:
            logger.error("Something is not OK with your url.")
            logger.debug(e)
            return

        except ValueError as e:
            logger.warning("Entered source was not a url.")
            logger.warning(e)

        # if it was not a web source, try if it is a file
        if not source_found:
            try:
                with open(source, 'r') as file:
                    text = file.read()
                logger.info("Found a file source for the node list.")
                source_found = True
            except FileNotFoundError as e:
                logger.exception(e)

        if not source_found:
            raise FileNotFoundError(f"Didn't find anything under the source you provided: {source}")

        # match the node public keys
        pattern = re.compile("[a-z0-9]{66}")
        nodes = re.finditer(pattern, text)

        # create an empty dict for nodes, connections is the number of connections to the target nodes
        nodes = {n.group(): {'connections': 0} for n in nodes}

        # instead of analyzing the nodes extracted from the data source, we can look at their neighbors
        # these neighbors can be seen as nodes, which distribute our capital to the target nodes
        if distributing_nodes:
            logger.info("Determining nodes that are well connected to the nodes from the node file.")

            # it makes sense to exclude large hubs in the search, because everybody is already connected to them
            if exclude_hubs:  # we exclude hubs in the neighbor analysis
                nodes_list = [n for n in nodes.keys()
                              if self.node.network.number_channels(n) < _settings.NUMBER_CHANNELS_DEFINING_HUB]
            else:
                nodes_list = nodes.keys()

            # we also want to avoid to count the nodes we are already connected to with blacklist_nodes
            blacklist_nodes = list(self.node.network.neighbors(self.node.pub_key))

            node_neighbors_list = self.node.network.nodes_in_neighborhood_of_nodes(nodes_list, blacklist_nodes)
            # set the number of connections to target nodes in the node dictionary
            nodes = {n[0]: {'connections': n[1]} for n in node_neighbors_list}

        nodes = self.add_metadata_and_remove_pruned(nodes, exclude_hubs)

        if not self.show_connected:
            nodes = self.exclude_connected_nodes(nodes)

        return nodes

    def add_metadata_and_remove_pruned(self, nodes, exclude_hubs=False):
        """
        Adds metadata like the number of channels, total capacity, ip address to the dict of nodes. If exclude_hubs is
        set to True, big nodes will be removed from nodes.
        :param nodes: dict
        :param exclude_hubs: bool
        :return: dict
        """
        nodes_new = {}
        number_nodes = len(nodes.keys())
        logger.info(f"Found {number_nodes} nodes for node recommendation.")
        if exclude_hubs:
            logger.info(f"Excluding hubs (defined by number of channels > {_settings.NUMBER_CHANNELS_DEFINING_HUB}).")
        for counter, (k, n) in enumerate(nodes.items()):
            try:
                # copy all the entries
                node_new = {k: n for k, n in n.items()}
                node_new['alias'] = self.node.network.node_alias(k)

                number_channels = self.node.network.number_channels(k)
                total_capacity = self.node.network.node_capacity(k)
                node_new['number_channels'] = number_channels
                if number_channels > 0:
                    node_new['total_capacity'] = total_capacity
                    node_new['capacity_per_channel'] = float(total_capacity) / number_channels
                    node_new['address'] = self.node.network.node_address(k)
                    node_new['distance'] = self.network_analysis.distance(self.node.pub_key, k)
                    if exclude_hubs:
                        if node_new['number_channels'] < _settings.NUMBER_CHANNELS_DEFINING_HUB:
                            nodes_new[k] = node_new
                    else:
                        nodes_new[k] = node_new
            except KeyError:  # it was a pruned node if it is not found in the graph and it shouldn't be recommended
                pass

        return nodes_new

    def exclude_connected_nodes(self, nodes):
        """
        Excludes already connected nodes from the nodes dict.
        :param nodes: dict, keys are node pub keys
        :return: dict
        """
        logger.debug("Filtering nodes which are not connected to us.")
        open_channels = self.node.get_open_channels()
        connected_node_pubkeys = set()
        filtered_nodes = OrderedDict()

        for k, v in open_channels.items():
            connected_node_pubkeys.add(v['remote_pubkey'])

        for k, v in nodes.items():
            if k not in connected_node_pubkeys:
                filtered_nodes[k] = v

        return filtered_nodes

    def print_flow_analysis(self, out_direction=True, number_of_nodes=20, forwarding_events=200):
        nodes = self.flow_analysis(out_direction, last_forwardings_to_analyze=forwarding_events)
        if len(nodes) == 0:
            logger.info(">>> Did not find historic recordings of forwardings, therefore cannot recommend any node.")
        else:
            sorted_nodes = OrderedDict(sorted(nodes.items(), key=lambda x: -x[1]['weight']))
            logger.debug(f"Found {len(sorted_nodes)} nodes in flow analysis.")
            self.print_nodes(nodes, number_of_nodes, 'rpk,nchan,cap,cpc,dist,alias')

    def print_good_old(self, number_of_nodes=20, sort_by='tot'):
        nodes = self.good_old()
        if len(nodes) == 0:
            logger.info(">>> Did not find historic recordings of forwardings, therefore cannot recommend any node.")
        else:
            sorted_nodes = OrderedDict(sorted(nodes.items(),
                                              key=lambda x: -x[1][print_node_format[sort_by]['dict_key']]))
            logger.debug(f"Found {len(sorted_nodes)} nodes as good old nodes.")
            logger.debug(f"Sorting nodes by {sort_by}.")
            self.print_nodes(sorted_nodes, number_of_nodes, 'rpk,tot,flow,nchan,cap,cpc,dist,alias')

    def print_nodefile(self, source, distributing_nodes, number_of_nodes=20, sort_by='cap'):
        nodes = self.nodefile(source, distributing_nodes)
        if len(nodes) == 0:
            logger.info("Did not find any nodes in the file/url provided.")
        else:
            logger.info(f"Showing nodes from source {source}.")
            sorted_nodes = OrderedDict(sorted(nodes.items(),
                                              key=lambda x: -x[1][print_node_format[sort_by]['dict_key']]))
            logger.debug(f"Found {len(sorted_nodes)} nodes as good old nodes.")
            logger.debug(f"Sorting nodes by {sort_by}.")
            self.print_nodes(sorted_nodes, number_of_nodes, 'rpk,con,nchan,cap,cpc,dist,alias')

    def print_nodes(self, nodes, number_of_nodes, columns):
        """
        General purpose printing function for flexible node tables.
        Colums is a string, which includes the order and items of columns with a comma delimiter like so:
        columns = "rpk,nchan,cap,cpc,a"
        :param nodes: dict
        :param number_of_nodes: int
        :param columns: str
        """
        logger.info("-------- Description --------")
        columns = columns.split(',')
        for c in columns:
            logger.info(f"{c:<10} {print_node_format[c]['description']}")
        logger.info(f"-------- Nodes (limited to {number_of_nodes} nodes) --------")

        # prepare the column header
        column_header_list = [f"{c:{print_node_format[c]['align']}{print_node_format[c]['width']}}" for c in columns]
        column_header = " ".join(column_header_list)
        logger.info(column_header)

        for ik, (k, v) in enumerate(nodes.items()):
            if ik > number_of_nodes:
                break
            # print each row in a formated way specified in the print_node dictionary
            row = [f"{v[print_node_format[c]['dict_key']]:{print_node_format[c]['format']}}"
                   for c in columns if c != 'rpk']
            row_string = " ".join(row)
            row_string = k + " " + row_string
            logger.info(row_string)

            if self.show_address:
                if v['address']:
                    logger.info('   ' + v['address'])
                else:
                    logger.info('   no address available')


if __name__ == '__main__':
    from lib.node import LndNode
    nd = LndNode()
    rn = RecommendNodes(nd)

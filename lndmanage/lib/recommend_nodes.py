import time
import re
from collections import OrderedDict

import urllib.request
from urllib.error import HTTPError

from lndmanage.lib.forwardings import ForwardingAnalyzer
from lndmanage.lib.network_info import NetworkAnalysis
from lndmanage import settings

import logging.config
logging.config.dictConfig(settings.logger_config)
logger = logging.getLogger(__name__)

# define printing shortcuts, alignments, and cutoffs
print_node_format = {
    'age': {
        'dict_key': 'age_days',
        'description': 'node age [days]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'alias': {
        'dict_key': 'alias',
        'description': 'alias',
        'width': 20,
        'format': '<30.29',
        'align': '^',
    },
    'cap': {
        'dict_key': 'total_capacity',
        'description': 'total capacity [btc]',
        'width': 7,
        'format': '7.3f',
        'align': '>',
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
        'description': 'capacity per channel [btc]',
        'width': 10,
        'format': '1.8f',
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
    'mburst': {
        'dict_key': 'metric_burst',
        'description': 'bursty old nodes',
        'width': 8,
        'format': '8.3f',
        'align': '>',
    },
    'msteady': {
        'dict_key': 'metric_steady',
        'description': 'steady nodes with lots of capacity opening',
        'width': 8,
        'format': '8.3f',
        'align': '>',
    },
    'nchan': {
        'dict_key': 'number_channels',
        'description': 'number of channels',
        'width': 6,
        'format': '6.0f',
        'align': '>',
    },
    'open': {
        'dict_key': 'openings',
        'description': 'number of channel openings in timeframe',
        'width': 6,
        'format': '6.0f',
        'align': '>',
    },
    'openmed': {
        'dict_key': 'opening_median_time',
        'description': 'median opening time [blocks]',
        'width': 7,
        'format': '7.2f',
        'align': '>',
    },
    'openavg': {
        'dict_key': 'opening_average_time',
        'description': 'average opening time [blocks]',
        'width': 7,
        'format': '7.2f',
        'align': '>',
    },
    'openrel': {
        'dict_key': 'relative_openings',
        'description': 'number of channel openings per number of total '
                       'channels of node in timeframe [1/time]',
        'width': 8,
        'format': '8.2f',
        'align': '>',
    },
    'opencap': {
        'dict_key': 'openings_total_capacity',
        'description': 'total capacity of channel openings in '
                       'timeframe [btc/time]',
        'width': 7,
        'format': '7.3f',
        'align': '>',
    },
    'opencaprel': {
        'dict_key': 'relative_total_capacity',
        'description': 'total capacity of channel openings per capacity '
                       'of node in timeframe [1/time]',
        'width': 11,
        'format': '11.2f',
        'align': '>',
    },
    'openavgcap': {
        'dict_key': 'openings_average_capacity',
        'description': 'average channel capacity of channel openings '
                       'in timeframe [btc/time]',
        'width': 11,
        'format': '11.8f',
        'align': '>',
    },
    'rpk': {
        'dict_key': 'remote_pubkey',
        'description': 'remote public key',
        'width': 66,
        'format': '<66',
        'align': '^',
    },
    'tot': {
        'dict_key': 'total_forwarding',
        'description': 'total forwarded [sat]',
        'width': 9,
        'format': '9d',
        'align': '>',
    },
    'sec': {
        'dict_key': 'new_second_neighbors',
        'description': 'new second neighbors',
        'width': 5,
        'format': '5d',
        'align': '>',
    },
    'weight': {
        'dict_key': 'weight',
        'description': 'forwarding weight',
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
        self.show_connected = show_connected
        self.show_address = show_addresses
        self.network_analysis = NetworkAnalysis(self.node)

    def print_flow_analysis(self, out_direction=True, number_of_nodes=20,
                            forwarding_events=200, sort_by='weight'):
        nodes = self.flow_analysis(
            out_direction, last_forwardings_to_analyze=forwarding_events)
        format_string = 'rpk,nchan,cap,cpc,alias'
        self.print_nodes(
            nodes, number_of_nodes, format_string, sort_by=sort_by)

    def print_good_old(self, number_of_nodes=20, sort_by='tot'):
        nodes = self.good_old()
        format_string = 'rpk,tot,flow,nchan,cap,cpc,alias'
        self.print_nodes(nodes, number_of_nodes, format_string, sort_by)

    def print_external_source(self, source, distributing_nodes,
                              number_of_nodes=20, sort_by='cap'):

        nodes = self.external_source(source, distributing_nodes)
        logger.info(f"Showing nodes from source {source}.")
        format_string = 'rpk,con,nchan,cap,cpc,alias'
        self.print_nodes(
            nodes, number_of_nodes, format_string, sort_by=sort_by)

    def print_channel_openings(self, from_days_ago=14, number_of_nodes=20,
                               sort_by='open'):

        nodes = self.channel_opening_statistics(from_days_ago)
        format_string = 'rpk,open,opencap,openrel,opencaprel,openavgcap,' \
                        'openmed,openavg,nchan,cap,cpc,age,alias'
        self.print_nodes(
            nodes, number_of_nodes, format_string, sort_by=sort_by)

    def print_second_neighbors(self, number_of_nodes=20, sort_by='sec'):
        nodes = self.second_neighbors(number_of_nodes)
        nodes = self.add_metadata_and_remove_pruned(nodes)
        format_string = 'rpk,sec,nchan,cap,cpc,alias'
        self.print_nodes(nodes, number_of_nodes, format_string, sort_by)

    def good_old(self):
        """
        Gives back a list of nodes to which we already had a good relationship
        with historic forwardings.

        :return: dict, nodes sorted by total amount forwarded
        """
        forwarding_analyzer = ForwardingAnalyzer(self.node)
        # analyze all historic forwardings
        forwarding_analyzer.initialize_forwarding_data(0, time.time())
        nodes = forwarding_analyzer.get_forwarding_statistics_nodes()
        nodes = self.add_metadata_and_remove_pruned(nodes)
        return nodes

    def flow_analysis(self, out_direction=True,
                      last_forwardings_to_analyze=200):
        """
        Does a flow analysis and suggests nodes which have demand for
        inbound liquidity.

        :param out_direction: bool, if True outward flowing
                              nodes are displayed
        :param last_forwardings_to_analyze: int, number of
                                            forwardings in analysis
        :return: nodes dict with metadata
        """
        forwarding_analyzer = ForwardingAnalyzer(self.node)
        # analyze all historic forwardings
        forwarding_analyzer.initialize_forwarding_data(0, time.time())
        nodes_in, nodes_out = forwarding_analyzer.simple_flow_analysis(
            last_forwardings_to_analyze)
        raw_nodes = nodes_out if out_direction else nodes_in
        nodes = self.add_metadata_and_remove_pruned(raw_nodes)
        return nodes

    def external_source(self, source, distributing_nodes=False,
                        exclude_hubs=True):
        """
        Parses a file/url (source) for node public keys and displays
        additional info.

        If distributing_nodes is set to True, nodes which are well connected to
        the nodes in the external source are displayed.

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
            raise FileNotFoundError(f"Didn't find anything under the source "
                                    f"you provided: {source}")

        # match the node public keys
        pattern = re.compile("[a-z0-9]{66}")
        nodes = re.finditer(pattern, text)

        # create an empty dict for nodes, connections is the number of
        # connections to the target nodes
        nodes = {n.group(): {'connections': 0} for n in nodes}

        # instead of analyzing the nodes extracted from the data source,
        # we can look at their neighbors these neighbors can be seen as nodes,
        # which distribute our capital to the target nodes
        if distributing_nodes:
            logger.info("Determining nodes that are well connected to the "
                        "nodes from the node file.")

            # it makes sense to exclude large hubs in the search,
            # because everybody is already connected to them
            if exclude_hubs:  # we exclude hubs in the neighbor analysis
                nodes_list = [
                    n for n in nodes.keys()
                    if self.node.network.number_channels(n) < settings.NUMBER_CHANNELS_DEFINING_HUB
                ]
            else:
                nodes_list = nodes.keys()

            # we also want to avoid to count the nodes we are already
            # connected to with blacklist_nodes
            blacklist_nodes = list(
                self.node.network.neighbors(self.node.pub_key))

            node_neighbors_list = \
                self.node.network.nodes_in_neighborhood_of_nodes(
                    nodes_list, blacklist_nodes)
            # set the number of connections to target nodes in
            # the node dictionary
            nodes = {n[0]: {'connections': n[1]} for n in node_neighbors_list}

        nodes = self.add_metadata_and_remove_pruned(nodes, exclude_hubs)

        return nodes

    def channel_opening_statistics(self, from_days_ago):
        """
        Fetches the channel opening statistics of the last `from_days_ago`
        days for the network analysis class and adds some
        additional heuristics.

        :param from_days_ago: int
        :return: dict, keys: node public keys, values: several heuristics
        """

        nodes = \
            self.network_analysis.calculate_channel_opening_statistics(
                from_days_ago)
        nodes = self.add_metadata_and_remove_pruned(nodes)

        # add the node age and other interesting metrics
        for n, nv in nodes.items():
            node_age = self.node.network.node_age(n)
            nodes[n]['age_days'] = node_age

            # goal of this metric:
            # find bust-like channel openings of older nodes
            # the motivation behind this is that this could be the behavior
            # of a node which first did testing on some service,
            # but then all of a sudden goes live, whose moment we want to catch

            nodes[n]['metric_burst'] = \
                nv['relative_total_capacity'] * \
                (nv['openings_total_capacity']) ** 2 * node_age \
                / max(1, nv['opening_median_time'])  # avoid division by zero

            # goal of this metric:
            # find steady nodes with lots of capacity opening the motivation
            # behind this is that this could be the behavior of experienced
            # node operators who dedicate themselves to their nodes and add
            # a lot of value to the network
            nodes[n]['metric_steady'] = nv['opening_median_time'] * (nv['openings_total_capacity'])**2

        return nodes

    def second_neighbors(self, number_of_nodes):
        """
        Returns a dict of nodes, which would give the most second neighbors
        when would be opened to them.

        :param number_of_nodes: number of nodes returned
        :type number_of_nodes: int
        :return: nodes
        :rtype: dict
        """
        node_tuples = self.network_analysis.nodes_most_second_neighbors(
            self.node.pub_key, number_of_nodes)
        nodes = {}
        for n in node_tuples:
            nodes[n[0]] = {'new_second_neighbors': n[1]}

        return nodes

    def add_metadata_and_remove_pruned(self, nodes, exclude_hubs=False):
        """
        Adds metadata like the number of channels, total capacity,
        ip address to the dict of nodes.

        This should be added to every node recommendation method,
        as it cleans out the obvious bad nodes to
        which we don't want to connect to.

        If exclude_hubs is set to True, big nodes will be removed from nodes.

        :param nodes: dict
        :param exclude_hubs: bool
        :return: dict
        """

        nodes_new = {}
        for counter, (k, n) in enumerate(nodes.items()):
            try:
                # copy all the entries
                node_new = {k: n for k, n in n.items()}
                node_new['alias'] = self.node.network.node_alias(k)

                number_channels = self.node.network.number_channels(k)
                total_capacity = self.node.network.node_capacity(k)
                node_new['number_channels'] = number_channels
                if number_channels > 0:
                    node_new['total_capacity'] = \
                        float(total_capacity) / 1E8  # in btc
                    node_new['capacity_per_channel'] = \
                        float(total_capacity) / number_channels / 1E8  # in btc
                    node_new['address'] = self.node.network.node_address(k)
                    node_new['distance'] = \
                        self.network_analysis.distance(self.node.pub_key, k)
                    if exclude_hubs:
                        if node_new['number_channels'] < settings.NUMBER_CHANNELS_DEFINING_HUB:
                            nodes_new[k] = node_new
                    else:
                        nodes_new[k] = node_new
            # it was a pruned node if it is not found in the graph and
            # it shouldn't be recommended
            except KeyError:
                pass

        if exclude_hubs:
            logger.info(f"Excluding hubs (defined by number of channels > "
                        f"{settings.NUMBER_CHANNELS_DEFINING_HUB}).")
        if not self.show_connected:
            nodes_new = self.exclude_connected_nodes(nodes_new)

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

    def print_nodes(self, nodes, number_of_nodes, columns, sort_by):
        """
        General purpose printing function for flexible node tables.

        Columns is a string, which includes the order and items of columns
        with a comma delimiter like so:

        columns = "rpk,nchan,cap,cpc,a"

        Sorting can be reversed by adding a "rev_" string before the
        sorting string.

        :param nodes: dict
        :param number_of_nodes: int
        :param columns: str
        :param sort_by: str, sorting string, these can be the keys
                             of the node dictionary
        """

        if len(nodes) == 0:
            logger.info(">>> Did not find any nodes.")
        else:
            logger.info(f"Found {len(nodes.keys())} nodes for "
                        f"node recommendation.")

        # some logic to reverse the sorting order
        # largest first
        reverse_sorting = True

        # if there is a marker 'rev_' in front, reverse the sorting
        if sort_by[:4] == 'rev_':
            reverse_sorting = False
            sort_by = sort_by[4:]
        nodes = OrderedDict(
            sorted(nodes.items(),
                   key=lambda x: x[1][print_node_format[sort_by]['dict_key']],
                   reverse=reverse_sorting))

        logger.info(f"Sorting nodes by {sort_by}.")

        logger.info("-------- Description --------")
        columns = columns.split(',')
        for c in columns:
            logger.info(f"{c:<10} {print_node_format[c]['description']}")
        logger.info(f"-------- Nodes (limited to "
                    f"{number_of_nodes} nodes) --------")

        # prepare the column header
        column_header_list = [
            f"{c:{print_node_format[c]['align']}{print_node_format[c]['width']}}"
            for c in columns]
        column_header = " ".join(column_header_list)
        logger.info(column_header)

        for ik, (k, v) in enumerate(nodes.items()):
            if ik > number_of_nodes:
                break
            # print each row in a formated way specified in the
            # print_node dictionary
            row = [
                f"{v[print_node_format[c]['dict_key']]:{print_node_format[c]['format']}}"
                   for c in columns if c != 'rpk']
            # add whitespace buffers between columns
            row_string = " ".join(row)
            row_string = k + " " + row_string
            logger.info(row_string)

            if self.show_address:
                if v['address']:
                    logger.info('   ' + v['address'])
                else:
                    logger.info('   no address available')


if __name__ == '__main__':
    from lndmanage.lib.node import LndNode
    nd = LndNode()
    rn = RecommendNodes(nd)

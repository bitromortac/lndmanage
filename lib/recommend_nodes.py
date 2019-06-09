from itertools import islice
from collections import OrderedDict
import time

import _settings

from lib.forwardings import ForwardingAnalyzer
from lib.listchannels import abbreviations, abbreviations_reverse

import logging.config
logging.config.dictConfig(_settings.logger_config)
logger = logging.getLogger(__name__)


class RecommendNodes(object):
    """
    A class to recommend nodes to connect to.
    """
    def __init__(self, node, show_connected=False, show_addresses=False):
        self.node = node
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

    def add_metadata_and_remove_pruned(self, nodes):
        """
        Adds metadata as the number of channels, total capacity, ip address to the dict of nodes.
        :param nodes: dict
        :return: dict
        """
        nodes_new = {}
        for k, n in nodes.items():
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
        print(len(filtered_nodes.keys()))

        return filtered_nodes

    def print_flow_analysis(self, out_direction=True, number_of_nodes=5, forwarding_events=200):
        nodes = self.flow_analysis(out_direction, last_forwardings_to_analyze=forwarding_events)
        if len(nodes) == 0:
            logger.info(">>> Did not find historic recordings of forwardings, therefore cannot recommend any node.")
        else:
            sorted_nodes = OrderedDict(sorted(nodes.items(), key=lambda x: -x[1]['weight']))
            logger.debug(f"Found {len(sorted_nodes)} nodes in flow analysis.")
            self.print_nodes_flow_analysis(sorted_nodes, number_of_nodes)

    def print_good_old(self, number_of_nodes=5, sort_by='tot'):
        nodes = self.good_old()
        if len(nodes) == 0:
            logger.info(">>> Did not find historic recordings of forwardings, therefore cannot recommend any node.")
        else:
            sorted_nodes = OrderedDict(sorted(nodes.items(), key=lambda x: -x[1][abbreviations_reverse[sort_by]]))
            logger.debug(f"Found {len(sorted_nodes)} nodes as good old nodes.")
            logger.debug(f"Sorting by {sort_by}.")
            self.print_nodes_good_old(sorted_nodes, number_of_nodes)

    # TODO: unite the print command, don't repeat
    def print_nodes_flow_analysis(self, nodes, number_of_nodes):
        logger.info("-------- Description --------")
        logger.info(
            f"{abbreviations['remote_pubkey']:<10} remote public key\n"
            f"{abbreviations['number_channels']:<10} number of channels\n"
            f"{abbreviations['total_capacity']:<10} total capacity [ksat]\n"
            f"{abbreviations['capacity_per_channel']:<10} capacity per channel [ksat]\n"
            f"{abbreviations['alias']:<10} alias\n"
        )
        logger.info(f"-------- Nodes (limited to {number_of_nodes} nodes) --------")
        logger.info(
            f"{abbreviations['remote_pubkey']:^66}"
            f"{abbreviations['number_channels']:>6}"
            f"{abbreviations['total_capacity']:>11}"
            f"{abbreviations['capacity_per_channel']:>10}"
            f"{abbreviations['alias']:>8}")
        n = 0
        for k, v in nodes.items():
            n += 1
            if n > number_of_nodes:
                break
            logger.info(
                f"{k} "
                f"{v['number_channels']: 5.0f} "
                f"{v['total_capacity'] / 1000: 10.0f} "
                f"{v['capacity_per_channel'] / 1000: 9.0f} "
                f"{v['alias']}"
            )
            if self.show_address:
                if v['address']:
                    logger.info('   ' + v['address'])
                else:
                    logger.info('   no address available')

    def print_nodes_good_old(self, nodes, number_of_nodes):
        logger.info("-------- Description --------")
        logger.info(
            f"{abbreviations['remote_pubkey']:<10} remote public key\n"
            f"{abbreviations['total_forwarding']:<10} total forwarded amount [sat]\n"
            f"{abbreviations['flow_direction']:<10} flow direction, value between [-1, 1], -1 is inwards\n"
            f"{abbreviations['number_channels']:<10} number of channels\n"
            f"{abbreviations['total_capacity']:<10} total capacity [ksat]\n"
            f"{abbreviations['capacity_per_channel']:<10} capacity per channel [ksat]\n"
            f"{abbreviations['alias']:<10} alias\n"
        )
        logger.info(f"-------- Nodes (limited to {number_of_nodes} nodes) --------")
        logger.info(
            f"{abbreviations['remote_pubkey']:^66}"
            f"{abbreviations['total_forwarding']:>10}"
            f"{abbreviations['flow_direction']:>6}"
            f"{abbreviations['number_channels']:>6}"
            f"{abbreviations['total_capacity']:>11}"
            f"{abbreviations['capacity_per_channel']:>10}"
            f"{abbreviations['alias']:>8}")
        n = 0
        for k, v in nodes.items():
            n += 1
            if n > number_of_nodes:
                break
            logger.info(
                f"{k} "
                f"{v['total_forwarding']:9d} "
                f"{v['flow_direction']: 3.2f} "
                f"{v['number_channels']: 5.0f} "
                f"{v['total_capacity'] / 1000: 10.0f} "
                f"{v['capacity_per_channel'] / 1000: 9.0f} "
                f"{v['alias']}"
            )
            if self.show_address:
                if v['address']:
                    logger.info('   ' + v['address'])
                else:
                    logger.info('   no address available')


if __name__ == '__main__':
    from lib.node import LndNode
    nd = LndNode()
    rn = RecommendNodes(nd)

from lndmanage.lib.network_info import NetworkAnalysis
from lndmanage.lib.node import LndNode
from lndmanage import settings

import logging.config
logging.config.dictConfig(settings.lndm_logger_config)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    node = LndNode()
    network_analysis = NetworkAnalysis(node)

    network_analysis.print_node_overview(node.pub_key)

    logger.info('-------- Nodes with highest capacity: --------')
    for n in network_analysis.get_sorted_nodes_by_property():
        logger.info(n)
    logger.info('-------- Nodes with highest degree: --------')
    for n in network_analysis.get_sorted_nodes_by_property(key='degree'):
        logger.info(n)
    logger.info('-------- Nodes with highest capacity/channel: --------')
    for n in network_analysis.get_sorted_nodes_by_property(key='capacity_per_channel', min_degree=10):
        logger.info(n)
    logger.info('-------- Nodes with lowest capacity/channel: --------')
    for n in network_analysis.get_sorted_nodes_by_property(key='capacity_per_channel', min_degree=20, decrementing=False):
        logger.info(n)
    logger.info('-------- Nodes with most user nodes: --------')
    for n in network_analysis.get_sorted_nodes_by_property(key='user_nodes', min_degree=20):
        logger.info(n)

    network_analysis.print_find_nodes_giving_most_secondary_hops(node.pub_key)


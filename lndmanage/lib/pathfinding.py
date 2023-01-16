from typing import Callable, List
from lndmanage.lib.exceptions import NoRoute

import networkx as nx

from lndmanage.lib.utilities import profiled
from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


@profiled
def dijkstra(graph: nx.Graph, source: str, target: str, weight: Callable) -> List[str]:
    """Wrapper for calculating a shortest path given a weight function.

    :param graph: networkx graph
    :param source: find a path from this key
    :param target: to this key
    :param weight: weight function, takes node_from (pubkey from), node_to (pubkey to), channel_info (edge information) as arguments

    :return: hops in terms of the node keys
    """
    path = nx.shortest_path(graph, source, target, weight=weight)

    if not path:
        raise NoRoute

    return path

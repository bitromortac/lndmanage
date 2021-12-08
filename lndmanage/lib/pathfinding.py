from typing import Callable, List

import networkx as nx

from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def dijkstra(graph: nx.Graph, source: str, target: str, weight: Callable) -> List[str]:
    """Wrapper for calculating a shortest path given a weight function.

    :param graph: networkx graph
    :param source: find a path from this key
    :param target: to this key
    :param weight: weight function, takes u (pubkey from), v (pubkey to), e (edge information) as arguments

    :return: hops in terms of the node keys
    """
    path = nx.shortest_path(graph, source, target, weight=weight)
    return path

import networkx as nx
import time
from lib.rating import ChannelRater
from lib.node import LndNode
from lib.pathfinding import ksp

if __name__ == '__main__':
    # TODO: create test lightning network graph (tests/graphs.py)
    node = LndNode()
    rater = ChannelRater()

    source = '000000000000000000000000000000000000000000000000000000000000000000'
    target = '000000000000000000000000000000000000000000000000000000000000000000'

    amount_msat = 100000
    weight_function = lambda v, u, e: rater.node_to_node_weight(v, u, e, amount_msat)

    print("Shortest path:")
    time_start = time.time()
    print(nx.shortest_path(node.network.graph, source, target, weight_function))
    time_end = time.time()
    print(time_end - time_start)

    print("K shortest paths with approximate costs [msats]:")
    paths, costs = ksp(node.network.graph, source, target, num_k=5, weight=weight_function)
    for path, cost in zip(paths, costs):
        print(path, cost)

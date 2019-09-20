import queue

import networkx as nx

from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def ksp_discard_high_cost_paths(graph, source, target, num_k, weight):
    """
    Wrapper for calculating k shortest paths given a weight function and discards paths with penalties.

    :param graph: networkx graph
    :param source: pubkey
    :param target: pubkey
    :param num_k: number of paths
    :param weight: weight function, takes u (pubkey from), v (pubkey to), e (edge information) as arguments
    :return: num_k lists of node pub_keys defining the path
    """
    final_routes = []
    routes, route_costs = ksp(graph, source, target, num_k, weight)
    logger.debug("Approximate costs [msat] of routes:")
    for r, rc in zip(routes, route_costs):
        if rc < settings.PENALTY:
            logger.debug(f"  {rc} msat: {r}")
            final_routes.append(r)
    return final_routes


# ksp algorithm is based on https://gist.github.com/ALenfant/5491853
def path_cost(graph, path, weight=None):
    pathcost = 0
    # print(path)
    for i in range(len(path)):
        if i > 0:
            edge = (path[i-1], path[i])
            if callable(weight):
                try:
                    e = graph[path[i-1]][path[i]]
                except KeyError:
                    e = None
                pathcost += weight(path[i-1], path[i], e)
            else:
                if weight != None:
                    pathcost += graph.get_edge_data(*edge)[weight]
                else:
                    pathcost += 1
    #print("pathcost", pathcost)
    #print()
    return pathcost


# ksp algorithm is based on https://gist.github.com/ALenfant/5491853
def ksp(graph, source, target, num_k, weight=None):
    graph_copy = graph.copy()
    # Shortest path from the source to the target
    A = [nx.shortest_path(graph_copy, source, target, weight=weight)]
    A_costs = [path_cost(graph_copy, A[0], weight)]

    # Initialize the heap to store the potential kth shortest path
    B = queue.PriorityQueue()

    for k in range(1, num_k):
        # The spur node ranges from the first node to the next to last node in the shortest path
        try:
            for i in range(len(A[k-1])-1):
                # Spur node is retrieved from the previous k-shortest path, k - 1
                spurNode = A[k-1][i]
                # The sequence of nodes from the source to the spur node of the previous k-shortest path
                rootPath = A[k-1][:i]

                # We store the removed edges
                removed_edges = []

                for path in A:
                    if len(path) - 1 > i and rootPath == path[:i]:
                        # Remove the links that are part of the previous shortest paths which share the same root path
                        edge = (path[i], path[i+1])
                        if not graph_copy.has_edge(*edge):
                            continue
                        removed_edges.append((edge, graph_copy.get_edge_data(*edge)))
                        graph_copy.remove_edge(*edge)

                # Calculate the spur path from the spur node to the sink
                try:
                    spurPath = nx.shortest_path(graph_copy, spurNode, target, weight=weight)

                    # Entire path is made up of the root path and spur path
                    totalPath = rootPath + spurPath
                    totalPathCost = path_cost(graph_copy, totalPath, weight)
                    # Add the potential k-shortest path to the heap
                    B.put((totalPathCost, totalPath))

                except nx.NetworkXNoPath:
                    pass

                #Add back the edges that were removed from the graph
                #for removed_edge in removed_edges:
                #    print(removed_edge)
                #    graph_copy.add_edge(
                #        *removed_edge[0],
                #        **removed_edge[1]
                #    )

            # Sort the potential k-shortest paths by cost
            # B is already sorted
            # Add the lowest cost path becomes the k-shortest path.
            while True:
                try:
                    cost_, path_ = B.get(False)
                    if path_ not in A:
                        A.append(path_)
                        A_costs.append(cost_)
                        break
                except queue.Empty:
                    break
        except IndexError:
            pass

    return A, A_costs

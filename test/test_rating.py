import unittest

from lndmanage.lib.rating import node_badness


class TestBadness(unittest.TestCase):
    def test_badness(self):
        node_hops = ['B', 'C', 'D', 'E', 'F', 'G']  # A is the very first node.

        def get_max_index(values):
          return max(range(len(values)), key=values.__getitem__)

        # Failed hop is from A->B: punish B the most
        failed_hop = 0
        badnesses = [node_badness(ni, failed_hop) for
            ni in range(len(node_hops))]
        self.assertEqual(0, get_max_index(badnesses))

        # Failed hop is from A->B: punish B and C the most
        failed_hop = 1
        badnesses = [node_badness(ni, failed_hop) for
            ni in range(len(node_hops))]
        self.assertEqual(0, get_max_index(badnesses))
        self.assertEqual(badnesses[0], badnesses[1])

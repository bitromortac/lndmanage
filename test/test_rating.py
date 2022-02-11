import unittest

from lndmanage.lib.rating import node_badness


class TestBadness(unittest.TestCase):
    def test_badness(self):
        node_hops = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
        failed_hop = 3
        for ni, _ in enumerate(node_hops):
            print(node_badness(ni, failed_hop))

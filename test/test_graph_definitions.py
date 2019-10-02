from unittest import TestCase

from lnregtest.lib.graph_testing import graph_test
from test.graph_definitions.star_ring_4_illiquid import nodes


class TestStarRing4Illiquid(TestCase):
    def test_graph(self):
        graph_test(nodes)

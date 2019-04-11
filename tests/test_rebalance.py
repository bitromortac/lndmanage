from unittest import TestCase

import _settings
from lib.node import LndNode
from lib.rebalance import Rebalancer, manual_rebalance

import logging.config
logging.config.dictConfig(_settings.logger_config)


class TestRebalance(TestCase):
    def setUp(self):
        self.node = LndNode()

    def test_manual_rebalance(self):
        manual_rebalance(self.node, 000000000000000000, 000000000000000000, amt=141248, number_of_routes=5)

    def test_auto_rebalance(self):
        rebalancer = Rebalancer(self.node, max_effective_fee_rate=1, budget_sat=10)
        invoice_r_hash = self.node.get_rebalance_invoice(memo='autorebalance test')
        rebalancer.rebalance_two_channels(000000000000000000, 000000000000000000, amt_sat=1,
                                          invoice_r_hash=invoice_r_hash, budget_sat=10)

    def test_rebalance(self):
        rebalancer = Rebalancer(self.node, max_effective_fee_rate=0.0001, budget_sat=50)
        channel_id = 000000000000000000
        fee = rebalancer.rebalance(channel_id)
        print(fee)


if __name__ == "__main__":
    node = LndNode()
    result = manual_rebalance(node, 000000000000000000, 000000000000000000, amt=10, number_of_routes=5)

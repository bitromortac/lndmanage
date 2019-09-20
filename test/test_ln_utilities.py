from unittest import TestCase
from lndmanage.lib.ln_utilities import channel_unbalancedness_and_commit_fee


class LnUtilityTest(TestCase):
    def test_unbalancedness_formula(self):
        self.assertAlmostEqual(
            channel_unbalancedness_and_commit_fee(
                500000, 1000000, 1000, False)[0], 0.0)
        self.assertAlmostEqual(
            channel_unbalancedness_and_commit_fee(
                500000, 1000000, 1000, True)[0], -0.002)
        self.assertAlmostEqual(
            channel_unbalancedness_and_commit_fee(
                600000, 1000000, 0, False)[0], -0.2)

from unittest import TestCase
from lndmanage.lib.ln_utilities import (
    local_balance_to_unbalancedness,
    unbalancedness_to_local_balance,
)


class LnUtilityTest(TestCase):
    def test_unbalancedness_formula(self):
        self.assertAlmostEqual(
            local_balance_to_unbalancedness(500000, 1000000, 1000, False)[0], 0.0
        )
        self.assertAlmostEqual(
            local_balance_to_unbalancedness(500000, 1000000, 1000, True)[0], -0.002
        )
        self.assertAlmostEqual(
            local_balance_to_unbalancedness(600000, 1000000, 0, False)[0], -0.2
        )

        # test inverse:
        ub = -0.2
        cap = 1000000
        cf = 100
        self.assertAlmostEqual(
            ub,
            local_balance_to_unbalancedness(
                unbalancedness_to_local_balance(ub, cap, 0, False)[0], cap, 0, False
            )[0],
        )
        self.assertAlmostEqual(
            ub,
            local_balance_to_unbalancedness(
                unbalancedness_to_local_balance(ub, cap, cf, True)[0], cap, cf, True
            )[0],
        )

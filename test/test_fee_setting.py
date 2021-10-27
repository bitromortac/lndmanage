from unittest import TestCase
import logging
import sys

from lndmanage.lib.fee_setting import delta_demand, delta_min, optimization_parameters

logger = logging.getLogger()
logger.level = logging.DEBUG
logger.addHandler(logging.StreamHandler(sys.stdout))


class TestFeeSetter(TestCase):
    def test_delta_min(self):
        cap = 2000000
        # maximal upward adjustment for empty local balance
        self.assertAlmostEqual(
            1 + optimization_parameters["delta_min_up"],
            delta_min(optimization_parameters, local_balance=0, capacity=cap),
        )
        # no adjustment if local balance is balance reserve
        self.assertAlmostEqual(
            1,
            delta_min(
                optimization_parameters,
                local_balance=optimization_parameters["local_balance_reserve"],
                capacity=cap,
            ),
        )
        # maximal downward adjustment for full local balance
        self.assertAlmostEqual(
            1 - optimization_parameters["delta_min_dn"],
            delta_min(optimization_parameters, local_balance=cap, capacity=cap),
        )

    def test_factor_demand_fee_rate(self):
        cap = 2000000
        interval_days = 7
        # maximal downward adjustment for full local balance and no demand
        self.assertAlmostEqual(
            1 - optimization_parameters["delta_min_dn"],
            delta_demand(
                optimization_parameters,
                time_interval=interval_days,
                amount_out=0,
                local_balance=cap,
                capacity=cap,
            ),
            places=6,
        )

        # maximal upward adjustment in the case of empty local balance and no demand
        self.assertAlmostEqual(
            1 + optimization_parameters["delta_min_up"],
            delta_demand(
                optimization_parameters,
                time_interval=interval_days,
                amount_out=0,
                local_balance=0,
                capacity=cap,
            ),
            places=6,
        )

        # optimal amount: no change
        self.assertAlmostEqual(
            1,
            delta_demand(
                optimization_parameters,
                time_interval=interval_days,
                amount_out=optimization_parameters["r_t"] * interval_days,
                local_balance=cap,
                capacity=cap,
            ),
            places=6,
        )

        # maximal demand: highest change
        self.assertAlmostEqual(
            optimization_parameters["delta_max"],
            delta_demand(
                optimization_parameters,
                time_interval=interval_days,
                amount_out=1000000,
                local_balance=cap,
                capacity=cap,
            ),
            places=6,
        )

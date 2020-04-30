from unittest import TestCase
import logging
import sys

from lndmanage.lib.fee_setting import delta_demand, delta_min, optimization_parameters

logger = logging.getLogger()
logger.level = logging.DEBUG
logger.addHandler(logging.StreamHandler(sys.stdout))


class TestFeeSetter(TestCase):

    def test_factor_demand_fee_rate(self):
        cap = 2000000
        interval_days = 7
        # test min cap function
        self.assertAlmostEqual(delta_min(optimization_parameters, 0, cap),
                               1 + optimization_parameters['delta_min_up'])
        self.assertAlmostEqual(
            delta_min(optimization_parameters, optimization_parameters['local_balance_reserve'], cap), 1)
        self.assertAlmostEqual(delta_min(optimization_parameters, cap, cap),
                               1 - optimization_parameters['delta_min_dn'])

        # test delta demand
        # no demand: full lb
        # this can fail, if the slope of delta_demand is too low, determined
        # by r_max
        self.assertAlmostEqual(
            delta_demand(optimization_parameters, time_interval=interval_days,
                         amount_out=0,
                         local_balance=cap,
                         capacity=cap),
            1 - optimization_parameters['delta_min_dn'],
            places=6)

        # no demand: empty lb
        self.assertAlmostEqual(
            delta_demand(optimization_parameters, time_interval=interval_days,
                         amount_out=0,
                         local_balance=0,
                         capacity=cap),
            1 + optimization_parameters['delta_min_up'],
            places=6)

        # optimal amount: no change
        self.assertAlmostEqual(
            delta_demand(optimization_parameters, time_interval=interval_days,
                         amount_out=optimization_parameters['r_t'] * interval_days,
                         local_balance=cap,
                         capacity=cap),
            1,
            places=6)

        # maximal demand: highest change
        self.assertAlmostEqual(
            delta_demand(optimization_parameters, time_interval=interval_days,
                         amount_out=optimization_parameters['r_max'] * interval_days,
                         local_balance=cap,
                         capacity=cap),
            optimization_parameters['delta_max'],
            places=6)

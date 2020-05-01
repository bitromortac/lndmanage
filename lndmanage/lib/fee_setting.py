import logging
import time

from lndmanage.lib.user import yes_no_question
from lndmanage.lib.forwardings import ForwardingAnalyzer

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

optimization_parameters = {
    'cltv': 14,  # blocks
    'min_base_fee': 20,  # msat
    'max_base_fee': 5000,  # msat
    'max_fee_rate': 0.001000,
    'min_fee_rate': 0.000004,
    'delta_max': 1.5,
    'delta_min_up': 0.05,
    'delta_min_dn': 0.50,
    'r_t': 100000 / 7,  # sat / day
    'r_max': 200000 / 7,  # sat / day  -- rule of thumb: about 2 * r_t
    'local_balance_reserve': 500000,  # sat
}


def delta_min(params, local_balance, capacity):
    """
    The cap from below for the delta_demand function.

    :param local_balance: local balance in sat
    :type local_balance: int
    :param capacity: capacity in sat
    :type capacity: int
    :return: minimal cap
    :rtype: float
    """
    if not local_balance <= capacity:
        raise ValueError(
            f"local balance must be lower than capacity "
            f"{local_balance} / {capacity}")

    # if we have small channels, which can't respect the reserve, lower the
    # reserve to a third of the channel
    if params['local_balance_reserve'] > capacity // 2:
        reserve = capacity // 3
    else:
        reserve = params['local_balance_reserve']

    # if local balance is below balance reserve, start to chage more fees
    if local_balance < params['local_balance_reserve']:
        x = params['delta_min_up'] / reserve
        return -x * (local_balance - reserve) + 1

    # if local balance is above balance reserve, charge less fees
    else:
        x = params['delta_min_dn'] / (
                    capacity - reserve)
        return -x * (local_balance - reserve) + 1


def delta_demand(params, time_interval, amount_out, local_balance, capacity):
    """
    Calculates a change factor for a channel by taking into account
    the amount transacted in a time interval compared to a target rate.

    The higher the amount forwarded, the larger the fee rate should be.
    :param time_interval: time interval in days
    :type time_interval: float
    :param amount_out: amount transacted outwards for the channel in sat
    :type amount_out: float
    :param local_balance: local balance in sat
    :type local_balance: int
    :param capacity: capacity in sat
    :type capacity: int

    :return:
    :rtype: float
    """
    r = amount_out / time_interval
    r_t = params['r_t']

    logger.info(
        f"    Outward forwarded amount: {amount_out:6.0f} "
        f"(rate {r:5.0f} / target rate {r_t:5.0f})")

    m = params['delta_max'] - 1.
    m /= (params['r_max'] / r_t - 1.)

    c = 1. + m * (r / r_t - 1.)

    mc = delta_min(params, local_balance, capacity)

    # cap from below
    if c < mc:
        return mc
    # cap from above
    elif c > params['delta_max']:
        return params['delta_max']
    else:
        return c


class FeeSetter(object):
    """
    Class for setting fees.
    """

    def __init__(self, node, from_days_ago=7, history_path='history.log',
                 parameters=None):
        """
        :param node: node instance
        :type node: `class`:lib.node.Node
        :param from_days_ago: forwarding history is taken over the past
            from_days_ago days
        :type from_days_ago: int
        :param history_path: path for the fee history log
        :type history_path: str
        :param parameters: fee algo parameters
        :type parameters: dict
        """

        # TODO: create a mocking node class
        # by default, channel fees are updated, not initialized
        self.node = node

        if parameters is None:
            self.params = optimization_parameters
        else:
            self.params = parameters

        self.history_path = history_path

        # initialize fee setter
        self.forwarding_analyzer = ForwardingAnalyzer(node)
        self.channel_fee_policies = node.get_channel_fee_policies()

        # determine time interval for forwardings analyzer to look back
        # for transactions
        self.time_end = time.time()
        self.time_start = self.time_end - from_days_ago * 24 * 60 * 60
        self.time_interval_days = from_days_ago
        self.forwarding_analyzer.initialize_forwarding_data(
            self.time_start, self.time_end)

        # get channel info
        self.channels = self.node.get_all_channels()
        self.channels_forwarding_stats = \
            self.forwarding_analyzer.get_forwarding_statistics_channels()

    def set_fees(self, init=False, reckless=False):
        """
        Sets channel fee policies considering different metrics like
        unbalancedness, flow, and demand.

        :param init: true if fees are set initially with this method
        :type init: bool
        :param reckless: if set, there won't be any user interaction
        :type reckless: bool

        :return: fee changes statistics
        :rtype: list[dict]
        """

        channel_fee_policies, stats = self.new_fee_policy(init)

        if reckless:
            set_fees = True
        else:
            logger.info("Do you want to set these fees? Enter [yes/no]:")
            set_fees = yes_no_question()

        if set_fees:
            logger.info("Have set new fee policy.")
            self.node.set_channel_fee_policies(channel_fee_policies)
            self.append_history(stats)
        else:
            logger.info("Didn't set new fee policy.")

        return stats

    def new_fee_policy(self, init=False):
        """
        Calculates and reports the changes to the new fee policy.

        :param init: when true, fee policy is initialized
        :type init: bool
        :return: (new channel policies, fee update statistics)
        :rtype: (dict, dict)
        """
        logger.info("Determining new channel policies based on demand.")
        logger.info(
            "Every channel will have a base fee of %d msat and cltv "
            "of %d.", self.params['min_base_fee'], self.params['cltv'])
        channel_fee_policies = {}

        stats = []

        for channel_id, channel_data in self.channels.items():
            channel_stats = self.channels_forwarding_stats.get(
                channel_id,
                None
            )
            if channel_stats is None:
                flow = 0
                fees_sat = 0
                total_forwarding_in = 0
                total_forwarding_out = 0
                total_forwarding = 0
                number_forwardings = 0
                number_forwardings_out = 0
            else:
                flow = channel_stats['flow_direction']
                fees_sat = channel_stats['fees_total'] / 1000
                total_forwarding_in = channel_stats['total_forwarding_in']
                total_forwarding_out = channel_stats['total_forwarding_out']
                total_forwarding = total_forwarding_in + total_forwarding_out
                number_forwardings = channel_stats['number_forwardings']
                number_forwardings_out = channel_stats[
                    'number_forwardings_out']
            lb = channel_data['local_balance']
            ub = channel_data['unbalancedness']
            capacity = channel_data['capacity']

            fee_rate = \
                self.channel_fee_policies[
                    channel_data['channel_point']]['fee_rate']
            base_fee_msat = \
                self.channel_fee_policies[
                    channel_data['channel_point']]['base_fee_msat']

            logger.info(">>> New channel policy for channel %s",
                        channel_id)
            logger.info(
                "    ub: %0.2f flow: %0.2f, fees: %1.3f sat, cap: %d sat, "
                "nfwd: %d, in: %d sat, out: %d sat.", ub, flow, fees_sat,
                capacity, number_forwardings, total_forwarding_in,
                total_forwarding_out)

            # FEE RATES
            factor_demand = delta_demand(self.params, self.time_interval_days,
                                         total_forwarding_out, lb, capacity)
            change_factor = factor_demand

            logger.info(
                "    Change factors: demand: %1.3f, "
                "unbalancedness %1.3f, flow: %1.3f. Weighted change: %1.3f",
                factor_demand, 0, 0, change_factor)

            # round down to 6 digits, as this is the expected data for
            # the api
            fee_rate_new = round(fee_rate * change_factor, 6)

            # if the fee rate is too low, cap it, as we don't want to
            # necessarily have too low fees, limit also from top
            fee_rate_new = max(self.params['min_fee_rate'], fee_rate_new)

            # if the fee rate is too high, cap it, as we don't want to
            # loose channels due to other parties thinking we are too greedy
            fee_rate_new = min(self.params['max_fee_rate'], fee_rate_new)

            # if we initialize the fee optimization, we want to start with
            # reasonable starting values
            if init:
                fee_rate_new = self.params['max_fee_rate'] / 2

            logger.info("    Fee rate: %1.6f -> %1.6f",
                        fee_rate, fee_rate_new)

            # BASE FEES
            factor_base_fee = self.factor_demand_base_fee(
                number_forwardings_out)
            base_fee_msat_new = base_fee_msat * factor_base_fee
            if init:
                base_fee_msat_new = self.params['min_base_fee']
            else:
                # limit from below
                base_fee_msat_new = int(
                    max(self.params['min_base_fee'], base_fee_msat_new))
                # limit from above
                base_fee_msat_new = int(
                    min(self.params['max_base_fee'], base_fee_msat_new))

            logger.info("    Base fee: %4d -> %4d (factor %1.3f)",
                        base_fee_msat, base_fee_msat_new, factor_base_fee)

            stats.append({
                'date': self.time_end,
                'channelid': channel_id,
                'total_in': total_forwarding_in,
                'total_out': total_forwarding_out,
                'ub': ub,
                'flow': flow,
                'fees': fees_sat,
                'cap': capacity,
                'fdem': factor_demand,
                'fub': 0,
                'fflow': 0,
                'wchange': change_factor,
                'fr': fee_rate,
                'frn': fee_rate_new,
                'nfwd': number_forwardings,
                'nfwdo': number_forwardings_out,
                'fbase': factor_base_fee,
                'bf': base_fee_msat,
                'bfn': base_fee_msat_new,
            })

            # give parsable output
            logger.info(
                f"stats: {self.time_end:.0f} {channel_id} "
                f"{total_forwarding_in} {total_forwarding_out} "
                f"{ub:.3f} {flow:.3f} "
                f"{fees_sat:.3f} {capacity} {factor_demand:.3f} "
                f"{0:.3f} {0:.3f} "
                f"{change_factor:.3f} {fee_rate:.6f} {fee_rate_new:.6f} "
                f"{number_forwardings} {number_forwardings_out} "
                f"{factor_base_fee:.3f} {base_fee_msat} {base_fee_msat_new}")

            channel_fee_policies[channel_data['channel_point']] = {
                'base_fee_msat': base_fee_msat_new,
                'fee_rate': fee_rate_new,
                'cltv': self.params['cltv'],
            }

        return channel_fee_policies, stats

    def factor_demand_base_fee(self, num_fwd_out):
        """
        Calculates a change factor by taking into account the number of
        transactions transacted in a time interval compared to a fixed number
        of transactions.

        :param num_fwd_out: number of outward forwardings
        :type num_fwd_out: int
        :return: [1-c_max, 1+c_max]
        :rtype: float
        """
        logger.info(
            "    Number of outward forwardings: %6.0f", num_fwd_out)
        c_min = 0.25  # change by 25% downwards
        c_max = 1.00  # change by 100% upwards

        num_fwd_target = 5 / 7
        c = c_min * ((num_fwd_out / self.time_interval_days)
                     / num_fwd_target - 1) + 1

        return min(c, 1 + c_max)

    def append_history(self, stats):
        # TODO: implement
        pass


if __name__ == '__main__':
    from lndmanage.lib.node import LndNode
    import logging.config
    from lndmanage import settings

    logging.config.dictConfig(settings.logger_config)

    nd = LndNode()
    fee_setter = FeeSetter(nd)
    fee_setter.set_fees()

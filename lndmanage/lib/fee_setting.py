import logging
import time
import os
import json

from lndmanage import settings
from lndmanage.lib.user import yes_no_question
from lndmanage.lib.forwardings import ForwardingAnalyzer

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

optimization_parameters = {
    'cltv': 40,  # blocks
    'min_base_fee': 20,  # msat
    'max_base_fee': 5000,  # msat
    'min_fee_rate': 0.000004,
    'max_fee_rate': 0.001000,
    'delta_max': 1.5,
    'delta_min_up': 0.05,
    'delta_min_dn': 0.50,
    'r_t': 100000 / 7,  # sat / day
    'local_balance_reserve': 300000,  # sat
    'delta_b_min': 0.25,
    'delta_b_max': 0.50,
    'delta_b': 0.5,
    'n_t': 4 / 7,
}


def delta_min(params, local_balance, capacity):
    """
    The cap from below for the delta_demand function.

    :param params: fee optimization parameters
    :type params: dict
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
    :param params: fee optimization parameters
    :type params: dict
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

    m = params['delta_min_dn']

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

    def __init__(self, node, from_days_ago=7, parameters=None):
        """
        :param node: node instance
        :type node: `class`:lib.node.Node
        :param from_days_ago: forwarding history is taken over the past
            from_days_ago days
        :type from_days_ago: int
        :param parameters: fee algo parameters
        :type parameters: dict
        """

        # TODO: create a mocking node class
        # by default, channel fees are updated, not initialized
        self.node = node

        self.history_path = os.path.join(settings.home_dir, 'fee_history.log')

        if parameters is None:
            self.params = optimization_parameters
        else:
            self.params = parameters

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

        channel_fee_policies, stats = self.new_fee_policies(init)

        if reckless:
            set_fees = True
        else:
            logger.info("Do you want to set these fees? Enter [yes/no]:")
            set_fees = yes_no_question()

        if set_fees:
            logger.info("Have set new fee policy.")
            self.node.set_channel_fee_policies(channel_fee_policies)
            self.append_to_history(stats)
        else:
            logger.info("Didn't set new fee policy.")

        return stats

    def new_fee_policies(self, init=False):
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

        # loop over channel peers
        for pk, cs in self.node.pubkey_to_channel_map().items():
            logger.info(f">>> Fee optimization for node {pk} "
                        f"({self.node.network.node_alias(pk)}):")
            # loop over channels with peer
            peer_capacity = 0
            peer_local_balance = 0
            peer_number_forwardings_out = 0
            peer_total_forwarding_out = 0
            cumul_base_fee = 0
            cumul_fee_rate = 0

            # accumulate information on a per peer basis
            for channel_id in cs:
                # collect channel info and stats
                channel_data = self.channels[channel_id]
                channel_stats = self.channels_forwarding_stats.get(
                    channel_id,
                    None
                )

                if channel_stats is None:
                    number_forwardings_out = 0
                    total_forwarding_out = 0
                else:
                    number_forwardings_out = channel_stats[
                        'number_forwardings_out']
                    total_forwarding_out = channel_stats[
                        'total_forwarding_out']

                peer_capacity += channel_data['capacity']
                peer_local_balance += channel_data['local_balance']
                peer_number_forwardings_out += number_forwardings_out
                peer_total_forwarding_out += total_forwarding_out

                cumul_fee_rate += \
                    self.channel_fee_policies[
                        channel_data['channel_point']]['fee_rate']
                cumul_base_fee += \
                    self.channel_fee_policies[
                        channel_data['channel_point']]['base_fee_msat']

            logger.info(f"    Channels with peer: {len(cs)}, "
                        f"total capacity: {peer_capacity}, "
                        f"total local balance: {peer_local_balance}")

            # calculate average base fee and fee rate
            base_fee_msat = int(cumul_base_fee / len(cs))
            fee_rate = round(cumul_fee_rate / len(cs), 6)

            # FEE RATES
            factor_demand = delta_demand(
                self.params,
                self.time_interval_days,
                peer_total_forwarding_out,
                peer_local_balance, peer_capacity
            )

            # round down to 6 digits, as this is the expected data for
            # the api
            fee_rate_new = round(fee_rate * factor_demand, 6)

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

            # BASE FEES
            factor_base_fee = self.factor_demand_base_fee(
                peer_number_forwardings_out)
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

            logger.info("    Fee rate change: %1.6f -> %1.6f (factor %1.3f)",
                        fee_rate, fee_rate_new, factor_demand)

            logger.info("    Base fee change: %4d -> %4d (factor %1.3f)",
                        base_fee_msat, base_fee_msat_new, factor_base_fee)

            # second loop through channels
            for channel_id in cs:
                channel_data = self.channels[channel_id]
                channel_stats = self.channels_forwarding_stats.get(
                    channel_id,
                    None
                )
                if channel_stats is None:
                    flow = 0
                    fees_sat = 0
                    total_forwarding_in = 0
                    total_forwarding_out = 0
                    number_forwardings = 0
                    number_forwardings_out = 0
                else:
                    flow = channel_stats['flow_direction']
                    fees_sat = channel_stats['fees_total'] / 1000
                    total_forwarding_in = channel_stats['total_forwarding_in']
                    total_forwarding_out = channel_stats[
                        'total_forwarding_out']
                    number_forwardings = channel_stats['number_forwardings']
                    number_forwardings_out = channel_stats[
                        'number_forwardings_out']

                lb = channel_data['local_balance']
                ub = channel_data['unbalancedness']
                capacity = channel_data['capacity']

                logger.info("  > Statistics for channel %s:", channel_id)
                logger.info(
                    "    ub: %0.2f, flow: %0.2f, fees: %1.3f sat, "
                    "cap: %d sat, lb: %d sat, nfwd: %d, in: %d sat, "
                    "out: %d sat.", ub, flow, fees_sat, capacity, lb,
                    number_forwardings, total_forwarding_in,
                    total_forwarding_out)

                stats.append({
                    'date': self.time_end,
                    'channelid': channel_id,
                    'total_in': total_forwarding_in,
                    'total_out': total_forwarding_out,
                    'lb': lb,
                    'ub': ub,
                    'flow': flow,
                    'fees': fees_sat,
                    'cap': capacity,
                    'fdem': factor_demand,
                    'fr': self.channel_fee_policies[
                        channel_data['channel_point']]['fee_rate'],
                    'frn': fee_rate_new,
                    'nfwd': number_forwardings,
                    'nfwdo': number_forwardings_out,
                    'fbase': factor_base_fee,
                    'bf': self.channel_fee_policies[
                        channel_data['channel_point']]['base_fee_msat'],
                    'bfn': base_fee_msat_new,
                })

                channel_fee_policies[channel_data['channel_point']] = {
                    'base_fee_msat': base_fee_msat_new,
                    'fee_rate': fee_rate_new,
                    'cltv': self.params['cltv'],
                }
            logger.info("")
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

        n = num_fwd_out / self.time_interval_days
        delta = 1 + optimization_parameters['delta_b'] * (
                n / optimization_parameters['n_t'] - 1)

        delta = max(1 - optimization_parameters['delta_b_min'],
                    min(delta, 1 + optimization_parameters['delta_b_max']))
        return delta

    def append_to_history(self, stats):
        """
        append_history adds the fee setting statistics to a pickle file.

        :param stats: fee statistics
        :type stats: dict
        """
        logger.debug("Saving fee setting stats to fee history.")
        with open(self.history_path, 'a') as f:
            json.dump(stats, f)
            f.write('\n')

    def read_history(self):
        """
        read_history is a function for unpickling the fee setting history.

        :return: list of fee setting statistics
        :rtype: list[dict]
        """
        with open(self.history_path, 'r') as f:
            history = []
            for i, line in enumerate(f):
                history.append(json.loads(line))
        return history


if __name__ == '__main__':
    from lndmanage.lib.node import LndNode
    import logging.config
    from lndmanage import settings

    logging.config.dictConfig(settings.logger_config)

    nd = LndNode('/home/user/.lndmanage/config.ini')
    fee_setter = FeeSetter(nd)
    fee_setter.set_fees()

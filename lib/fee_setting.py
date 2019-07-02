import logging
import time

from lib.user import yes_no_question
from lib.forwardings import ForwardingAnalyzer

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class FeeSetter(object):
    """
    Class for setting fees.
    """
    def __init__(self, node):
        """
            :param: node: `class`:lib.node.Node
        """
        self.node = node
        self.forwarding_analyzer = ForwardingAnalyzer(node)
        self.channel_fee_settings = node.get_channel_fee_policies()

    def set_fees_demand(self, cltv=20, base_fee_msat=30, from_days_ago=7,
                        min_fee_rate=0.000001, reckless=False):
        """
        Sets channel fee rates by estimating an economic demand factor.

        The change factor is based on four quantities, the unbalancedness,
        the fund flow, the fees collected (in a certain time frame) and
        the remaining remote balance.

        :param cltv: int
        :param base_fee_msat: int
        :param from_days_ago: int, forwarding history is taken over the past
                                   from_days_ago
        :param min_fee_rate: float, the fee rate will be not set lower than
                                    this amount
        :param reckless: bool, if set, there won't be any user interaction
        """
        time_end = time.time()
        time_start = time_end - from_days_ago * 24 * 60 * 60

        self.forwarding_analyzer.initialize_forwarding_data(
            time_start, time_end)

        channels = self.node.get_all_channels()
        channels_forwarding_stats = \
            self.forwarding_analyzer.get_forwarding_statistics_channels()
        channel_fee_policies = self.fee_rate_change(
            channels, channels_forwarding_stats, base_fee_msat, cltv,
            min_fee_rate)

        if not reckless:
            logger.info("Do you want to set these fees? Enter [yes/no]:")
            if yes_no_question():
                self.node.set_channel_fee_policies(channel_fee_policies)
        else:
            self.node.set_channel_fee_policies(channel_fee_policies)

    def fee_rate_change(self, channels, channels_forwarding_stats,
                        base_fee_msat, cltv, min_fee_rate=0.000001):
        """
        Calculates and reports the changes of the new fee policy.

        :param channels: dict with basic channel information
        :param channels_forwarding_stats: dict with forwarding information
        :param base_fee_msat: int
        :param cltv: int
        :param min_fee_rate: float, the fee rate will be not smaller than this
                                    parameter
        :return: dict, channel fee policies
        """
        logger.info("Determining new channel policies based on demand.")
        logger.info("Every channel will have a base fee of %d msat and cltv "
                    "of %d.", base_fee_msat, cltv)

        channel_fee_policies = {}

        for channel_id, channel_data in channels.items():
            channel_stats = channels_forwarding_stats.get(channel_id, None)
            if channel_stats is None:
                flow = 0
                fees_sat = 0
            else:
                flow = channel_stats['flow_direction']
                fees_sat = channel_stats['fees_total'] // 1000

            ub = channel_data['unbalancedness']
            remote_balance = channel_data['remote_balance']
            remote_balance = max(1, remote_balance)  # avoid zero division

            fee_rate = \
                self.channel_fee_settings[
                    channel_data['channel_point']]['fee_rate']

            logger.info(">>> New channel policy for channel %s", channel_id)
            logger.info(
                "    ub: %0.2f flow: %0.2f, fees: %d sat, rb: %d sat. ",
                ub, flow, fees_sat, remote_balance)

            factor_demand = self.factor_demand(fees_sat, remote_balance)
            factor_unbalancedness = self.factor_unbalancedness(ub)
            factor_flow = self.factor_unbalancedness(flow)

            # define weights
            wgt_demand = 1.2
            wgt_ub = 0.7
            wgt_flow = 0.5

            # calculate weighted change
            weighted_change = (
                wgt_ub * factor_unbalancedness +
                wgt_flow * factor_flow +
                wgt_demand * factor_demand
            ) / (wgt_ub + wgt_flow + wgt_demand)

            logger.info(
                "    Change factors: demand: %1.3f, "
                "unbalancedness %1.3f, flow: %1.3f. Weighted change: %1.3f",
                factor_demand, factor_unbalancedness, factor_flow,
                weighted_change)

            fee_rate_new = fee_rate * weighted_change
            fee_rate_new = max(min_fee_rate, fee_rate_new)

            logger.info("    Fee rate: %1.6f -> %1.6f",
                        fee_rate, fee_rate_new)

            channel_fee_policies[channel_data['channel_point']] = {
                'base_fee_msat': base_fee_msat,
                'fee_rate': fee_rate_new,
                'cltv': cltv,
            }

        return channel_fee_policies

    @staticmethod
    def factor_unbalancedness(ub):
        """
        Calculates a change rate for the unbalancedness.

        The lower the unbalancedness, the lower the fee rate should be.
        This encourages outward flow through this channel.

        :param ub: float, in [-1 ... 1]
        :return: float, [1-c_max, 1+c_max]

        """
        # maximal change
        c_max = 0.25
        # give unbalancedness a more refined weight
        rescale = 0.5

        c = 1 + ub * rescale
        # limit the change
        if c > 1:
            return min(c, 1 + c_max)
        else:
            return max(c, 1 - c_max)

    @staticmethod
    def factor_flow(flow):
        """
        Calculates a change rate for the flow rate.

        If forwardings are predominantly flowing outward, we want to increase
        the fee rate, because there seems to be demand.

        :param flow: float, [-1 ... 1]
        :return: float, [1-c_max, 1+c_max]
        """
        c_max = 0.25
        rescale = 0.5
        c = 1 + flow * rescale

        # limit the change
        if c > 1:
            return min(c, 1 + c_max)
        else:
            return max(c, 1 - c_max)

    @staticmethod
    def factor_demand(fees_sat, remote_balance_sat):
        """
        Calculates a change factor by taking into account the fees collected
        and the remote balance left.

        The higher the fees collected, the larger the fee rate should be. Also
        if there is only a small amount of remote balance left, we also want to
        increase the fee rate.

        The model for the change rate is determined by a linear function:
        change = m * fee / remote_balance + t

        :param fees_sat:
        :param remote_balance_sat:
        :return: float, [1-c_max, 1+c_max]
        """

        # remote balance should have an influence also in the case when
        # the fees were zero
        fees_sat = max(fees_sat, 0.1)
        # maximal change in percent: 1-c_max ... 1+c_max
        c_max = 0.25
        # model:
        # change = m * fee / remote_balance + t

        # empirical parameter (determined by channel with most demand)
        fee_per_remote_max = 1E-5

        m = 2 * c_max / fee_per_remote_max
        # chosen such, that at zero fees, we get c = 1 - c_max
        t = 1 - c_max

        c = m * (fees_sat / remote_balance_sat) + t

        if c > 1:
            return min(c, 1 + c_max)
        else:
            return c


if __name__ == '__main__':
    from lib.node import LndNode
    import logging.config
    import _settings
    logging.config.dictConfig(_settings.logger_config)

    nd = LndNode()
    fee_setter = FeeSetter(nd)
    fee_setter.set_fees_demand()

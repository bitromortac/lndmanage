import logging

import _settings
from lib.exceptions import NoRouteError, RebalanceFailure, DryRunException, PaymentTimeOut, TooExpensive
from lib.routing import Router
from lib.user import yes_no_question

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def manual_rebalance(node, channel_id_from, channel_id_to, amt, number_of_routes=10):
    """
    Attempts several times to rebalance channel_id_from to channel_id_to with amt satoshis,
    asking for permission.

    :param node: object
    :param channel_id_from:
    :param channel_id_to:
    :param amt: amount in satoshi
    :param number_of_routes:
    """

    router = Router(node)
    amt_msat = amt * 1000
    logger.info(
        f"-------- Attempting advanced rebalancing of {amt_msat} msats"
        f" from channel {channel_id_from} to {channel_id_to}. --------")

    routes = router.get_routes_for_rebalancing(
        channel_id_from, channel_id_to, amt_msat, number_of_routes
    )
    logger.info("Found {} cheapest routes".format(len(routes)))

    node.update_blockheight()
    for r in routes:
        logger.info("Do you want to try the following route with a fee of {} msats [Y/n]?".format(r.total_fee_msat))
        if yes_no_question():
            node.self_payment_zero_invoice(
                r, memo=f"lndmanage: Rebalance from {channel_id_from} to {channel_id_to}: {amt} sats")


class Rebalancer(object):
    """
    Implements methods of rebalancing. A max_effective_fee_rate can be set, which limits the fee rate
    paid for a rebalance. The effective fee rate is (base_fee + fee_rate * amt)/amt. A fee cap can be
    defined by budget_sat. Individual and total rebalancing are not allowed to go over this amount.

    * auto_rebalance_channel: rebalances a channel into the direction that makes it more balanced.

    :param node: :class:`lib.node.Node` instance
    :param max_effective_fee_rate: caps the fees at rates specified here
    :param budget_sat: cap for the fees paid
    """

    def __init__(self, node, max_effective_fee_rate, budget_sat):
        self.node = node
        self.channel_list = node.get_unbalanced_channels()
        self.router = Router(self.node)
        self.max_effective_fee_rate = max_effective_fee_rate
        self.budget_sat = budget_sat

    def rebalance_two_channels(self, channel_id_from, channel_id_to, amt_sat, invoice_r_hash, budget_sat,
                               dry=False):
        """
        Rebalances from channel_id_from to channel_id_to with an amount of amt_sat. A prior created invoice hash
        has to be given. The budget_sat sets the maxmimum fees that will be paid. A dry run can be done.

        :param channel_id_from:
        :param channel_id_to:
        :param amt_sat:
        :param invoice_r_hash:
        :param budget_sat:
        :param dry: bool
        :return: total fees for the whole rebalance
        """

        amt_msat = amt_sat * 1000

        count = 0
        while True:
            # only attempt a fixed number of times
            count += 1
            if count > 10:
                raise RebalanceFailure

            routes = self.router.get_routes_for_rebalancing(
                channel_id_from, channel_id_to, amt_msat)
            if len(routes) == 0:
                raise NoRouteError
            else:
                r = routes[0]

            logger.info(f"Next route: total fee: {r.total_fee_msat / 1000:3.3f} sat, fee rate: {r.total_fee_msat / r.total_amt_msat:1.6f},"
                        f" hops: {len(r.channel_hops)}")
            logger.info(f"   Channel hops: {r.channel_hops}")

            rate = r.total_fee_msat / r.total_amt_msat
            if rate > self.max_effective_fee_rate:
                logger.info(f"   Channel is too expensive. "
                            f"Rate: {rate:.6f}, requested max rate: {self.max_effective_fee_rate:.6f}")
                raise TooExpensive
            if r.total_fee_msat > budget_sat * 1000:
                logger.info(f"   Channel is too expensive. "
                            f"Fee: {r.total_fee_msat:.6f} msats, requested max fee: {budget_sat:.6f} msats")
                raise TooExpensive

            if not dry:
                try:
                    result = self.node.send_to_route(r, invoice_r_hash)
                except PaymentTimeOut:
                    # TODO: handle payment timeout properly
                    raise PaymentTimeOut

                logger.debug(f"Payment error: {result.payment_error}.")

                if result.payment_error:
                    # determine the channel/node that reported a failure
                    reporting_channel_id = self.node.handle_payment_error(result.payment_error)
                    if reporting_channel_id:
                        # determine the following channel that failed
                        index_failed_channel = r.channel_hops.index(reporting_channel_id)
                        failed_channel_id = r.channel_hops[index_failed_channel]

                        if failed_channel_id in [channel_id_from, channel_id_to]:
                            raise Exception(f"Own channel failed. Something is wrong. "
                                            f"Failing channel: {failed_channel_id}")

                        failed_channel_source = r.node_hops[index_failed_channel - 1]
                        failed_channel_target = r.node_hops[index_failed_channel]
                        logger.info(f"   Failed channel: {failed_channel_id}")
                        logger.debug(f"   Failed channel between {failed_channel_source} and {failed_channel_target}")
                        logger.debug(r.node_hops)
                        logger.debug(r.channel_hops)
                        # remember the bad channel for next routing
                        self.router.channel_rater.add_bad_channel(
                            failed_channel_id, failed_channel_source, failed_channel_target)

                    else:  # usually UnknownNextPeer
                        # then add all the inner hops to the blacklist
                        logger.error("   Unknown next peer somewhere in route.")
                        inner_hops = r.channel_hops[1:-1]
                        for i_hop, hop in enumerate(inner_hops):
                            failed_channel_source = r.node_hops[i_hop]
                            failed_channel_target = r.node_hops[i_hop + 1]
                            self.router.channel_rater.add_bad_channel(
                                hop, failed_channel_source, failed_channel_target)
                    continue
                else:
                    logger.debug(result.payment_preimage)
                    logger.info("Success!\n")
                    return r.total_fee_msat
            else:  # dry
                raise DryRunException

    def get_rebalance_candidates(self, direction):
        """
        Determines channels, which can be used to rebalance a channel. The direction sets,
        if the to be balanced channel has more inbound or outbound capacity.

        :param direction: -1 / 1
        :return: list of channels
        """

        # filters all unbalanced channels
        rebalance_candidates = [
            c for c in self.channel_list
            if -1.0 * direction * c['unbalancedness'] > _settings.UNBALANCED_CHANNEL + 1E-6
        ]

        # filters by max_effective_fee_rate
        rebalance_candidates = [
            c for c in rebalance_candidates
            if self.effective_fee_rate(c['amt_to_balanced'], c['fees']['base'], c['fees']['rate'])
            < self.max_effective_fee_rate
        ]
        # TODO: make it possible to specify a strategy
        rebalance_candidates.sort(key=lambda x: x['amt_to_balanced'], reverse=True)
        # rebalance_candidates.sort(key=lambda x: x['fees']['rate'])
        return rebalance_candidates

    @staticmethod
    def effective_fee_rate(amt_sat, base, rate):
        """
        Calculates the effective fee rate. (base_fee + fee_rate * amt) / amt

        :param amt_sat:
        :param base:
        :param rate:
        :return: effective fee rate
        """

        amt_msat = amt_sat * 1000
        assert not (amt_msat == 0)
        rate = (base + rate * amt_msat / 1000000) / amt_msat
        return rate

    @staticmethod
    def print_rebalance_candidates(rebalance_candidates):
        logger.debug(f"-------- Found {len(rebalance_candidates)} candidates for rebalancing --------")
        for c in rebalance_candidates:
            logger.debug(
                f" ub:{c['unbalancedness']: 4.2f} atb:{c['amt_to_balanced']: 9d}"
                f" l:{c['local_balance']: 9d} r:{c['remote_balance']: 9d} b:{c['fees']['base']: 6d}"
                f" r:{c['fees']['rate']/1E6: 1.6f} c:{c['chan_id']} a:{c['alias']}")

    def extract_channel_info(self, chan_id):
        """
        Gets the channel info (policy, capacity, nodes) from the graph. Sometimes this could fail.
        :param chan_id:
        :return: channel information
        """
        channel_info = None
        for c in self.channel_list:
            if c['chan_id'] == chan_id:
                channel_info = c
        if channel_info is None:
            raise KeyError("Channel not found (already closed?)")
        return channel_info

    @staticmethod
    def is_balanced(unbalancedness):
        return abs(unbalancedness) < _settings.UNBALANCED_CHANNEL

    @staticmethod
    def get_source_and_target_channels(channel_one, channel_two, rebalance_direction):
        if rebalance_direction < 0:
            source = channel_one
            target = channel_two
        else:
            source = channel_two
            target = channel_one

        return source, target

    def rebalance(self, channel_id, dry=False, chunksize=1.0):
        """
        Automatically rebalances a selected channel with a fee cap of self.budget_sat and self.max_effective_fee_rate.
        Rebalancing candidates are selected among all channels which are unbalanced in the other direction.
        Uses :func:`self.rebalance_two_channels` for rebalancing a pair of channels.

        At the moment, rebalancing channels are tried one at a time, so it is not yet optimized for the
        lowest possible fees.

        The chunksize allows for partitioning of the individual rebalancing attempts into smaller pieces than
        would maximally possible (chunksize=1.0). The smaller the chunksize the higher is the success rate,
        but the rebalancing cost increases.

        :param channel_id:
        :param dry: bool: if set, then there's a dry run
        :param chunksize: float between 0 and 1
        :return: fees for rebalancing
        """

        if not (0.0 <= chunksize <= 1.0):
            raise ValueError("Chunk size must be between 0.0 and 1.0")

        logger.info(f">>> Trying to rebalance channel {channel_id} with a max rate of {self.max_effective_fee_rate}"
                    f"and a max fee of {self.budget_sat} sat.")
        logger.info(f">>> Chunk size is set to {chunksize}.")

        if dry:
            logger.info(f">>> This is a dry run, nothing to fear.")

        unbalanced_channel_info = self.extract_channel_info(channel_id)

        # amount to balanced is the absolute amount the channel balance is off to be at 50:50
        amt_target_original = unbalanced_channel_info['amt_to_balanced']
        amt_target = int(amt_target_original)
        # unbalancedness means -1: totally outbound, 0: balanced, 1: totally inbound
        unbalancedness = unbalanced_channel_info['unbalancedness']

        if self.is_balanced(unbalancedness):
            logger.info(f"Channel already balanced. Unbalancedness: {unbalancedness}")
            return None

        logger.info(f">>> Amount required for the channel to be balanced is {int(amt_target_original)} sat.")

        rebalance_direction = (1, -1)[unbalancedness < 0]  # maps to the sign of unbalancedness
        rebalance_candidates = self.get_rebalance_candidates(rebalance_direction)

        logger.info(f">>> There are {len(rebalance_candidates)} channels with which we can rebalance (look at logfile).")
        logger.info(f">>> We will try to rebalance with them one after the other.")
        logger.info(f">>> NOTE: only individual rebalance requests are optimized for fees,"
                    f" use --dry flag to get a feeling (we aim here for a high success rate).")
        logger.info(f">>> Rebalancing can take some time. Please be patient!\n")

        self.print_rebalance_candidates(rebalance_candidates)

        # create an invoice with a zero amount for all rebalance attempts (reduces number of invoices)
        invoice_r_hash = self.node.get_rebalance_invoice(
            memo=f"lndmanage: Rebalance of channel {channel_id}.")

        total_fees_msat = 0

        # loop over the rebalancing candidates
        for c in rebalance_candidates:

            if 1.0 * amt_target / amt_target_original <= 0.1:
                logger.info(f"Goal is reached. Rebalancing done. Total fees were {total_fees_msat} msats.")
                break

            if total_fees_msat >= self.budget_sat * 1000:
                raise RebalanceFailure("Fee budget exhausted")

            source_channel, target_channel = self.get_source_and_target_channels(
                channel_id, c['chan_id'], rebalance_direction)

            if amt_target_original > c['amt_to_balanced']:
                amt = int(c['amt_to_balanced'] * chunksize)
            else:
                amt = int(amt_target_original * chunksize)

            logger.info(f"-------- Rebalance from {source_channel} to {target_channel} with {amt} sats --------")
            logger.info(f"Need to still rebalance {amt_target} sat to reach the goal of {amt_target_original} sat."
                        f" Fees paid up to now: {total_fees_msat} msats.")

            # attempt the rebalance
            try:
                # be up to date with the blockheight, otherwise could lead to cltv errors
                self.node.update_blockheight()
                total_fees_msat += self.rebalance_two_channels(
                    source_channel, target_channel, amt, invoice_r_hash, self.budget_sat, dry=dry)
                amt_target -= amt
                invoice_r_hash = self.node.get_rebalance_invoice(memo=f"lndmanage: Rebalance of channel {channel_id}.")
            except NoRouteError:
                logger.error("There was no route cheap enough or with enough capacity.\n")
            except DryRunException:
                logger.info("Would have tried this route now, but it was a dry run.\n")
            except RebalanceFailure:
                logger.error("Failed to rebalance with this channel.\n")
            except TooExpensive:
                logger.error("Too expensive.\n")

        return total_fees_msat


if __name__ == "__main__":
    import logging.config
    logging.config.dictConfig(_settings.logger_config)

    from lib.node import LndNode
    nd = LndNode()
    chan = 000000000000000000
    max_fee_rate = 0.0001
    rebalancer = Rebalancer(nd, max_fee_rate, budget_sat=20)
    fee = rebalancer.rebalance(chan)
    print(fee)

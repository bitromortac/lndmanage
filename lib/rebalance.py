import logging
import math

import _settings
from lib.exceptions import NoRouteError, RebalanceFailure, DryRunException, PaymentTimeOut, TooExpensive
from lib.routing import Router

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


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
        has to be given. The budget_sat sets the maxmimum fees in sat that will be paid. A dry run can be done.

        :param channel_id_from: int
        :param channel_id_to: int
        :param amt_sat: int
        :param invoice_r_hash: bytes
        :param budget_sat: int
        :param dry: bool
        :return: total fees for the whole rebalance in msat
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

            logger.info(f"Next route: total fee: {r.total_fee_msat / 1000:3.3f} sat,"
                        f" fee rate: {r.total_fee_msat / r.total_amt_msat:1.6f},"
                        f" hops: {len(r.channel_hops)}")
            logger.info(f"   Channel hops: {r.channel_hops}")

            rate = r.total_fee_msat / r.total_amt_msat
            if rate > self.max_effective_fee_rate:
                logger.info(f"   Channel is too expensive. "
                            f"Rate: {rate:.6f}, requested max rate: {self.max_effective_fee_rate:.6f}")
                raise TooExpensive

            if r.total_fee_msat > budget_sat * 1000:
                logger.info(f"   Channel is too expensive. "
                            f"Fee: {r.total_fee_msat:.6f} msat, requested max fee: {budget_sat:.6f} msat")
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
                        try:
                            index_failed_channel = r.channel_hops.index(reporting_channel_id)
                            failed_channel_id = r.channel_hops[index_failed_channel]
                        except ValueError:
                            logger.error("Failed channel not even in list of channel hops (lnd issue?).")
                            continue
                        # check if a failed channel was our own, which should, in principle, not happen
                        if failed_channel_id in [channel_id_from, channel_id_to]:
                            raise RebalanceFailure(
                                f"Own channel failed. Something is wrong. This is likely due to a wrong"
                                f" accounting for the channel reserve and will be fixed in the future. Try"
                                f" with smaller absolute target. Failing channel: {failed_channel_id}")

                        # determine the nodes involved in the channel
                        failed_channel_source = r.node_hops[index_failed_channel - 1]
                        failed_channel_target = r.node_hops[index_failed_channel]
                        logger.info(f"   Failed channel: {failed_channel_id}")
                        logger.debug(f"   Failed channel between nodes {failed_channel_source}"
                                     f" and {failed_channel_target}")
                        logger.debug(f"    Node hops {r.node_hops}")
                        logger.debug(f"    Channel hops {r.channel_hops}")

                        # remember the bad channel for next routing
                        self.router.channel_rater.add_bad_channel(
                            failed_channel_id, failed_channel_source, failed_channel_target)

                    else:  # usually the case of UnknownNextPeer
                        # add all the inner hops to the blacklist
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

    def get_rebalance_candidates(self, channel_id, local_balance_change, allow_unbalancing=False, strategy=None):
        """
        Determines channels, which can be used to rebalance a channel. If the local_balance_change is negative,
        the local balance of the to be balanced channel is tried to be reduced. This method determines channels
        with which we can rebalance by ideally balancing also the counterparty. However, this is not always possible
        so one can also specify to allow unbalancing until an unbalancedness of UNBALANCED_CHANNEL and no more.
        One can also specify a strategy, which determines the order of channels of the rebalancing process.

        :param channel_id: the channel id of the to be rebalanced channel
        :param local_balance_change: amount by which the local balance of channel should change in sat
        :param allow_unbalancing: bool
        :param strategy: str,
            None: By default, counterparty channels are sorted such that the ones unbalanced in the opposite direction
                  are chosen first, such that they also get balanced. After them also the other channels, unbalanced in
                  the non-ideal direction are tried (if allowed by allow_unbalancing).
            'feerate': Channels are sorted by increasing peer fee rate.
            'affordable': Channels are sorted by the absolute affordable amount.
        :return: list of channels
        """
        rebalance_candidates = []

        # select the proper lower bound (allows for unbalancing a channel)
        if allow_unbalancing:
            lower_bound = -_settings.UNBALANCED_CHANNEL  # target is a bit into the non-ideal direction
        else:
            lower_bound = 0  # target is complete balancedness
        # TODO: allow for complete depletion

        # determine the direction, -1: channel is sending, 1: channel is receiving
        direction = -math.copysign(1, local_balance_change)

        # logic to shift the bounds accordingly into the different rebalancing directions
        for k, c in self.channel_list.items():
            if direction * c['unbalancedness'] > lower_bound:
                if allow_unbalancing:
                    c['amt_affordable'] = int(
                        c['amt_to_balanced'] + direction * _settings.UNBALANCED_CHANNEL * c['capacity'] / 2)
                else:
                    c['amt_affordable'] = c['amt_to_balanced']
                rebalance_candidates.append(c)

        # filter channels, which can't afford a rebalance
        rebalance_candidates = [c for c in rebalance_candidates if not c['amt_affordable'] == 0]

        # filters by max_effective_fee_rate, as this is the minimal fee rate to be paid
        rebalance_candidates = [
            c for c in rebalance_candidates
            if self.effective_fee_rate(c['amt_affordable'], c['peer_base_fee'], c['peer_fee_rate'])
            < self.max_effective_fee_rate]

        # need to make sure we don't rebalance with the same channel
        rebalance_candidates = [
            c for c in rebalance_candidates if c['chan_id'] != channel_id]

        # need to remove multiply connected nodes, if the counterparty channel should receive (can't control last hop)
        if local_balance_change < 0:
            rebalance_candidates = [
                c for c in rebalance_candidates if not self.node_is_multiply_connected(c['remote_pubkey'])]

        if strategy == 'most-affordable-first':
            rebalance_candidates.sort(key=lambda x: direction * x['amt_affordable'], reverse=True)
        elif strategy == 'lowest-feerate-first':
            rebalance_candidates.sort(key=lambda x: x['peer_fee_rate'])
        elif strategy == 'match-unbalanced':
            rebalance_candidates.sort(key=lambda x: -direction * x['unbalancedness'])
        else:
            rebalance_candidates.sort(key=lambda x: direction * x['amt_to_balanced'], reverse=True)
        # TODO: for each rebalance candidate calculate the shortest path with absolute fees and sort

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
        logger.debug(f"-------- Description --------")
        logger.debug(
            "cid: channel id\n"
            "ub: unbalancedness (see --help)\n"
            "atb: amount to be balanced [sat]\n"
            "aaf: amount affordable [sat]\n"
            "l: local balance [sat]\n"
            "r: remote balance [sat]\n"
            "bf: peer base fee [msat]\n"
            "fr: peer fee rate\n"
            "a: alias"
        )

        logger.debug(f"-------- Candidates in order of rebalance attempts --------")
        for c in rebalance_candidates:
            logger.debug(
                f"cid:{c['chan_id']} "
                f"ub:{c['unbalancedness']: 4.2f} "
                f"atb:{c['amt_to_balanced']: 9d} "
                f"aaf:{c['amt_affordable']: 9d} "
                f"l:{c['local_balance']: 9d} "
                f"r:{c['remote_balance']: 9d} "
                f"bf:{c['peer_base_fee']: 6d} "
                f"fr:{c['peer_fee_rate']/1E6: 1.6f} "
                f"a:{c['alias']}")

    def extract_channel_info(self, chan_id):
        """
        Gets the channel info (policy, capacity, nodes) from the graph.
        :param chan_id:
        :return: channel information
        """
        channel_info = None
        for k, c in self.channel_list.items():
            if c['chan_id'] == chan_id:
                channel_info = c
        if channel_info is None:
            raise KeyError("Channel not found (already closed?)")
        return channel_info

    @staticmethod
    def get_source_and_target_channels(channel_one, channel_two, rebalance_direction):
        if rebalance_direction < 0:
            source = channel_one
            target = channel_two
        else:
            source = channel_two
            target = channel_one

        return source, target

    @staticmethod
    def maximal_local_balance_change(target, unbalanced_channel_info):
        """
        Tries to find out the amount to maximally send/receive given the relative target
        and channel reserve constraints.

        The target is expressed as a relative quantity between -1 and 1:
        -1: channel has only local balance
        0: 50:50 balanced
        1: channel has only remote balance

        :param target: positive or negative float, interpreted in terms of unbalancedness [-1...1]
        :param unbalanced_channel_info: dict, information on the channel
        :return: int: positive or negative amount in sat (encodes the decrease/increase in the local balance)
        """
        # both parties need to maintain a channel reserve of 1% according to BOLT 2
        channel_reserve = int(0.01 * unbalanced_channel_info['capacity'])

        if target:
            # a commit fee needs to be only respected by the channel initiator
            commit_fee = 0 if not unbalanced_channel_info['initiator'] else unbalanced_channel_info['commit_fee']

            # first naively calculate the local balance change to fulfill the requested target
            local_balance_target = int(unbalanced_channel_info['capacity'] * 0.5 * (-target + 1.0) - commit_fee)
            local_balance_change = local_balance_target - unbalanced_channel_info['local_balance']

            # TODO: clarify exact definitions of dust and htlc_cost (somewhat guessing here)
            # related: https://github.com/lightningnetwork/lnd/issues/1076
            # https://github.com/lightningnetwork/lightning-rfc/blob/master/03-transactions.md#fees
            dust = 700
            htlc_weight = 172
            number_htlcs = 2
            htlc_cost = int(number_htlcs * htlc_weight * unbalanced_channel_info['fee_per_kw'] / 1000)
            logger.debug(f">>> Assuming a dust limit of {dust} sat and an HTLC cost of {htlc_cost} sat.")

            # we can only send the local balance less the channel reserve (if above the dust limit),
            # less the cost to enforce the HTLC
            can_send = max(0, unbalanced_channel_info['local_balance']
                           - max(dust, channel_reserve) - htlc_cost - 1)

            # we can only receive the remote balance less the channel reserve (if above the dust limit)
            can_receive = max(0, unbalanced_channel_info['remote_balance']
                              - max(dust, channel_reserve) - 1)

            logger.debug(f">>> Channel can send {can_send} sat and receive {can_receive} sat.")

            # check that we respect and enforce the channel reserve
            if local_balance_change > 0 and abs(local_balance_change) > can_receive:
                local_balance_change = can_receive
            if local_balance_change < 0 and abs(local_balance_change) > can_send:
                local_balance_change = -can_send

            amt_target_original = int(local_balance_change)
        else:
            # just use the already calculated optimal amount for 50:50 balancedness
            amt_target_original = unbalanced_channel_info['amt_to_balanced']

        return amt_target_original

    def node_is_multiply_connected(self, pub_key):
        """
        Checks if the node is connected to us via several channels.

        :param pub_key: str, public key
        :return: bool, true if number of channels to the node is larger than 1
        """
        channels = 0
        for k, c in self.channel_list.items():
            if c['remote_pubkey'] == pub_key:
                channels += 1
        if channels > 1:
            return True
        else:
            return False

    def rebalance(self, channel_id, dry=False, chunksize=1.0, target=None, allow_unbalancing=False, strategy=None):
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
        :param target: specifies unbalancedness after rebalancing
        :param allow_unbalancing: bool, allows counterparty channels to get a little bit unbalanced
        :param strategy: lets you select a strategy for rebalancing order
        :return: int, fees in msat paid for rebalancing
        """
        if not (0.0 <= chunksize <= 1.0):
            raise ValueError("Chunk size must be between 0.0 and 1.0")

        logger.info(f">>> Trying to rebalance channel {channel_id} with a max rate of {self.max_effective_fee_rate}"
                    f" and a max fee of {self.budget_sat} sat.")
        logger.info(f">>> Chunk size is set to {chunksize}.")

        if dry:
            logger.info(f">>> This is a dry run, nothing to fear.")

        unbalanced_channel_info = self.channel_list[channel_id]

        # if a target is given and it is set close to -1 or 1, then we need to think about the channel reserve
        initial_local_balance_change = self.maximal_local_balance_change(target, unbalanced_channel_info)

        if initial_local_balance_change == 0:
            logger.info(f"Channel already balanced.")
            return None

        local_balance_change_left = initial_local_balance_change  # copy the original target
        rebalance_direction = math.copysign(1, initial_local_balance_change)  # 1: receive, -1: send

        logger.info(f">>> The channel status before rebalancing is lb:{unbalanced_channel_info['local_balance']} sat "
                    f"rb:{unbalanced_channel_info['remote_balance']} sat "
                    f"cap:{unbalanced_channel_info['capacity']} sat.")
        logger.debug(f">>> Commit fee {unbalanced_channel_info['commit_fee']} sat."
                     f" We opened channel: {unbalanced_channel_info['initiator']}."
                     f" Channel reserve: {int(unbalanced_channel_info['capacity'] * 0.01)} sat.")
        logger.debug(f">>> The change in local balance towards the requested target"
                     f" (ub={target if target else 0.0:3.2f})"
                     f" is {initial_local_balance_change} sat.")
        commit_fee = 0
        if unbalanced_channel_info['initiator']:
            commit_fee = unbalanced_channel_info['commit_fee']

        expected_target = - 2 * ((unbalanced_channel_info['local_balance'] + initial_local_balance_change + commit_fee)
                                 / float(unbalanced_channel_info['capacity']) - 0.5)
        logger.info(f">>> Trying to change the local balance by {initial_local_balance_change} sat.\n"
                    f"    The expected target is {expected_target:3.2f} (respecting channel reserve),"
                    f" requested target is {0 if not target else target:3.2f}.")

        if (initial_local_balance_change > 0
                and self.node_is_multiply_connected(unbalanced_channel_info['remote_pubkey'])):
            raise RebalanceFailure("Receiving rebalancing of multiply connected node channel not supported.\n"
                                   "The reason is that the last hop (channel) can't be controlled by us.\n"
                                   "See https://github.com/lightningnetwork/lnd/issues/2966 and \n"
                                   "https://github.com/lightningnetwork/lightning-rfc/blob/master/"
                                   "04-onion-routing.md#non-strict-forwarding.\n"
                                   "Tip: keep only the best channel to the node and then rebalance.")


        rebalance_candidates = self.get_rebalance_candidates(
            channel_id, local_balance_change_left, allow_unbalancing=allow_unbalancing, strategy=strategy)

        logger.info(f">>> There are {len(rebalance_candidates)} channels with which we can rebalance (look at logs).")

        self.print_rebalance_candidates(rebalance_candidates)

        logger.info(f">>> We will try to rebalance with them one after the other.")
        logger.info(f">>> NOTE: only individual rebalance requests are optimized for fees:\n"
                    f"    this means that there can be rebalances with less fees afterwards,\n"
                    f"    so take a look at the dry runs first, i.e. without the --reckless flag,\n"
                    f"    and set --max-fee-sat and --max-fee-rate accordingly.\n"
                    f"    You may also specify a rebalancing strategy by the --strategy flag.")
        logger.info(f">>> Rebalancing can take some time. Please be patient!\n")

        # create an invoice with a zero amount for all rebalance attempts (reduces number of invoices)
        invoice_r_hash = self.node.get_rebalance_invoice(
            memo=f"lndmanage: Rebalance of channel {channel_id}.")

        total_fees_msat = 0

        # loop over the rebalancing candidates
        for c in rebalance_candidates:

            if total_fees_msat >= self.budget_sat * 1000:
                raise RebalanceFailure("Fee budget exhausted")

            source_channel, target_channel = self.get_source_and_target_channels(
                channel_id, c['chan_id'], rebalance_direction)

            if abs(local_balance_change_left) > abs(c['amt_affordable']):
                amt = int(abs(c['amt_affordable']) * chunksize)
            else:
                amt = int(local_balance_change_left * chunksize)

            logger.info(f"-------- Rebalance from {source_channel} to {target_channel} with {amt} sat --------")
            logger.info(f"Need to still rebalance {local_balance_change_left} sat to reach the goal"
                        f" of {initial_local_balance_change} sat."
                        f" Fees paid up to now: {total_fees_msat} msat.")

            # attempt the rebalance
            try:
                # be up to date with the blockheight, otherwise could lead to cltv errors
                self.node.update_blockheight()
                total_fees_msat += self.rebalance_two_channels(
                    source_channel, target_channel, abs(amt), invoice_r_hash, self.budget_sat, dry=dry)
                local_balance_change_left -= amt

                if 1.0 * local_balance_change_left / initial_local_balance_change <= 0.1:
                    logger.info(f"Goal is reached. Rebalancing done. Total fees were {total_fees_msat} msat.")
                    break
                else:
                    invoice_r_hash = self.node.get_rebalance_invoice(
                        memo=f"lndmanage: Rebalance of channel {channel_id}.")
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

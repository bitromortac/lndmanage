import logging
import math
from typing import TYPE_CHECKING, Optional, List, Tuple

from lndmanage.lib.routing import Router
from lndmanage.lib import exceptions
from lndmanage.lib.exceptions import (
    RebalanceFailure,
    NoRoute,
    NoRebalanceCandidates,
    RebalanceCandidatesExhausted,
    RebalancingTrialsExhausted,
    DryRun,
    PaymentTimeOut,
    TooExpensive,
    DuplicateRoute,
    MultichannelInboundRebalanceFailure,
)
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Rebalancer(object):
    """
    Implements methods for rebalancing.

    A max_effective_fee_rate can be set, which limits the fee rate paid for
    a rebalance. The effective fee rate is (base_fee + fee_rate * amt)/amt.
    A fee cap can be defined by budget_sat. Individual and total rebalancing
    are not allowed to go over this amount.
    """
    def __init__(self, node: 'LndNode', max_effective_fee_rate: float, budget_sat: int):
        """
        :param node: node instance
        :param max_effective_fee_rate: maximum effective fee rate paid
        :param budget_sat: rebalancing budget
        """
        self.node = node
        self.channel_list = {}
        self.router = Router(self.node)
        self.router.channel_rater.add_bad_node(self.node.pub_key)
        self.max_effective_fee_rate = max_effective_fee_rate
        self.budget_sat = budget_sat

    def rebalance_two_channels(
            self, channel_id_from: int, channel_id_to: int, amt_sat: int,
            payment_hash: bytes, payment_address: bytes, budget_sat: int,
            dry=False
    ) -> int:
        """
        Rebalances from channel_id_from to channel_id_to with an amount of
        amt_sat.

        A prior created payment_hash has to be given. The budget_sat sets
        the maxmimum fees in sat that will be paid. A dry run can be done.

        :param channel_id_from: channel sending
        :param channel_id_to: channel receiving
        :param amt_sat: amount to be sent in sat
        :param payment_hash: payment hash
        :param payment_address: payment hash
        :param budget_sat: budget for the rebalance
        :param dry: specifies if dry run

        :return: total fees for the whole rebalance in msat

        :raises TemporarayChannelFailure: no liquidity along path
        :raises UnknownNextPeer: a routing node didn't where to forward
        :raises DuplicateRoute: the same route was already tried
        :raises NoRoute: no route was found from source to destination
        :raises TooExpensive: the circular payment would exceed the fee limits
        :raises PaymentTimeOut: the payment timed out
        :raises DryRun: attempt was just a dry run
        """
        amt_msat = amt_sat * 1000
        previous_route_channel_hops = None

        count = 0
        while True:
            # only attempt a fixed number of times
            count += 1
            if count > settings.REBALANCING_TRIALS:
                raise RebalancingTrialsExhausted

            # method is set to external-mc to use mission control based
            # pathfinding
            routes = self.router.get_routes_for_rebalancing(
                channel_id_from, channel_id_to, amt_msat, method='external-mc')

            if not routes:
                raise NoRoute
            else:
                # take only the first route from routes
                r = routes[0]

            if previous_route_channel_hops == r.channel_hops:
                raise DuplicateRoute("Have tried this route already.")
            previous_route_channel_hops = r.channel_hops

            logger.info(
                f"Next route: total fee: {r.total_fee_msat / 1000:3.3f} sat, "
                f"fee rate: {r.total_fee_msat / r.total_amt_msat:1.6f}, "
                f"hops: {len(r.channel_hops)}")
            logger.info(f"   Channel hops: {r.channel_hops}")

            rate = r.total_fee_msat / r.total_amt_msat
            if rate > self.max_effective_fee_rate:
                logger.info(
                    f"   Channel is too expensive (rate too high). Rate: {rate:.6f}, "
                    f"requested max rate: {self.max_effective_fee_rate:.6f}")
                raise TooExpensive

            if r.total_fee_msat > budget_sat * 1000:
                logger.info(
                    f"   Channel is too expensive (budget exhausted). Total fee of route: "
                    f"{r.total_fee_msat / 1000:.3f} sat, budget: {budget_sat:.3f} sat")
                raise TooExpensive

            result = None
            failed_hop = None
            if not dry:
                try:
                    result = self.node.send_to_route(r, payment_hash, payment_address)
                except PaymentTimeOut:
                    raise PaymentTimeOut
                except exceptions.TemporaryChannelFailure as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.UnknownNextPeer as e:
                    failed_hop = int(e.payment.failure.failure_source_index + 1)
                except exceptions.ChannelDisabled as e:
                    failed_hop = int(e.payment.failure.failure_source_index + 1)
                except exceptions.FeeInsufficient as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                else:
                    logger.debug(f"Preimage: {result.preimage.hex()}")
                    logger.info("Success!\n")
                    return r.total_fee_msat

                if failed_hop:
                    failed_channel_id = r.hops[failed_hop]['chan_id']
                    failed_node_source = r.node_hops[failed_hop]
                    failed_node_target = r.node_hops[failed_hop + 1]

                    if failed_channel_id in [channel_id_from, channel_id_to]:
                        raise RebalanceFailure(
                            f"Own channel failed. Something is wrong. "
                            f"This is likely due to a wrong accounting "
                            f"for the channel reserve and will be fixed "
                            f"in the future. "
                            f"Try with smaller absolute target. "
                            f"Failing channel: {failed_channel_id}")

                    # determine the nodes involved in the channel
                    logger.info(f"   Failed channel: {failed_channel_id}")
                    logger.debug(
                        f"   Failed channel between nodes "
                        f"{failed_node_source} and "
                        f"{failed_node_target}")
                    logger.debug(f"   Node hops {r.node_hops}")
                    logger.debug(f"   Channel hops {r.channel_hops}")

                    # remember the bad channel for next routing
                    self.router.channel_rater.add_bad_channel(
                        failed_channel_id, failed_node_source,
                        failed_node_target)
            else:  # dry
                raise DryRun

    def _get_rebalance_candidates(self, channel_id: int, local_balance_change: int,
                                  allow_unbalancing=False, strategy=Optional[str]):
        """
        Determines channels, which can be used to rebalance a channel.

        If the local_balance_change is negative, the local balance of the to
        be balanced channel is tried to be reduced. This method determines
        channels with which we can rebalance by ideally balancing also the
        counterparty. However, this is not always possible  so one can also
        specify to allow unbalancing until an unbalancedness of
        UNBALANCED_CHANNEL and no more. One can also specify a strategy,
        which determines the order of channels of the rebalancing process.

        :param channel_id: the channel id of the to be rebalanced channel
        :param local_balance_change: amount by which the local balance of
            channel should change in sat
        :param allow_unbalancing: if unbalancing of channels should be allowed
        :param strategy:
            None: By default, counterparty channels are sorted such that the
                  ones unbalanced in the opposite direction are chosen first,
                  such that they also get balanced. After them also the other
                  channels, unbalanced in the non-ideal direction are tried
                  (if allowed by allow_unbalancing).
            'feerate': Channels are sorted by increasing peer fee rate.
            'affordable': Channels are sorted by the affordable amount.
        :type strategy: str

        :return: list of channels
        :rtype: list
        """
        rebalance_candidates = []

        # select the proper lower bound of unbalancedness we allow for
        # the rebalance candidate channel (allows for unbalancing a channel)
        if allow_unbalancing:
            # target is a bit into the non-ideal direction
            lower_bound = -settings.UNBALANCED_CHANNEL
        else:
            # target is perfect balance
            lower_bound = 0
        # TODO: allow for complete depletion

        # determine the direction we use the rebalance candidate for:
        # -1: rebalance channel is sending, 1: rebalance channel is receiving
        direction = -math.copysign(1, local_balance_change)

        # logic to shift the bounds accordingly into the different
        # rebalancing directions
        for k, c in self.channel_list.items():
            if direction * c['unbalancedness'] > lower_bound:
                if allow_unbalancing:
                    c['amt_affordable'] = int(
                        c['amt_to_balanced'] +
                        direction * settings.UNBALANCED_CHANNEL
                        * c['capacity'] / 2)
                else:
                    c['amt_affordable'] = c['amt_to_balanced']
                rebalance_candidates.append(c)

        # filter channels, which can't afford a rebalance
        rebalance_candidates = [
            c for c in rebalance_candidates if not c['amt_affordable'] == 0]

        # filters by max_effective_fee_rate, as this is the minimal fee rate
        # to be paid
        rebalance_candidates = [
            c for c in rebalance_candidates
            if self._effective_fee_rate(
                c['amt_affordable'], c['peer_base_fee'], c['peer_fee_rate'])
            < self.max_effective_fee_rate]

        # need to make sure we don't rebalance with the same channel
        rebalance_candidates = [
            c for c in rebalance_candidates if c['chan_id'] != channel_id]

        # need to remove multiply connected nodes, if the counterparty channel
        # should receive (can't control last hop)
        if local_balance_change < 0:
            rebalance_candidates = [
                c for c in rebalance_candidates
                if not self._node_is_multiple_connected(c['remote_pubkey'])]

        if strategy == 'most-affordable-first':
            rebalance_candidates.sort(
                key=lambda x: direction * x['amt_affordable'], reverse=True)
        elif strategy == 'lowest-feerate-first':
            rebalance_candidates.sort(
                key=lambda x: x['peer_fee_rate'])
        elif strategy == 'match-unbalanced':
            rebalance_candidates.sort(
                key=lambda x: -direction * x['unbalancedness'])
        else:
            rebalance_candidates.sort(
                key=lambda x: direction * x['amt_to_balanced'], reverse=True)
        # TODO: for each rebalance candidate calculate the shortest path
        #  with absolute fees and sort

        return rebalance_candidates

    @staticmethod
    def _effective_fee_rate(amt_sat: int, base_fee: float, fee_rate: float) -> float:
        """
        Calculates the effective fee rate: (base_fee + fee_rate * amt) / amt

        :param amt_sat: amount in sat
        :param base_fee: base fee in sat
        :param fee_rate: fee rate

        :return: effective fee rate
        """
        amt_msat = amt_sat * 1000
        assert not (amt_msat == 0)
        fee_rate = (base_fee + fee_rate * amt_msat / 1000000) / amt_msat
        return fee_rate

    @staticmethod
    def _print_rebalance_candidates(rebalance_candidates: List[dict]):
        """
        Prints rebalance candidates.

        :param rebalance_candidates:
        """
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

        logger.debug(f"-------- Candidates in order of rebalance attempts "
                     f"--------")
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

    def _extract_channel_info(self, chan_id: int) -> dict:
        """
        Gets the channel info (policy, capacity, nodes) from the graph.
        :param chan_id: channel id

        :return: channel information
        """
        # TODO: make more pythonic
        channel_info = None
        for k, c in self.channel_list.items():
            if c['chan_id'] == chan_id:
                channel_info = c
        if channel_info is None:
            raise KeyError("Channel not found (already closed?)")
        return channel_info

    @staticmethod
    def _get_source_and_target_channels(channel_one: int, channel_two: int,
                                        rebalance_direction: float) -> Tuple[int, int]:
        """
        Determines what the sending and receiving channel ids are.

        :param channel_one: first channel
        :param channel_two: second channel
        :param rebalance_direction: positive, if receiving, negative if sending
        :return: sending and receiving channel
        """
        if rebalance_direction < 0:
            source = channel_one
            target = channel_two
        else:
            source = channel_two
            target = channel_one

        return source, target

    @staticmethod
    def _maximal_local_balance_change(unbalancedness_target: float,
                                      unbalanced_channel_info: dict) -> int:
        """
        Tries to find out the amount to maximally send/receive given the
        relative target and channel reserve constraints for channel balance
        candidates.

        The target is expressed as a relative quantity between -1 and 1:
        -1: channel has only local balance
        0: 50:50 balanced
        1: channel has only remote balance

        :param unbalancedness_target:
            interpreted in terms of unbalancedness [-1...1]
        :param unbalanced_channel_info: fees, capacity, initiator info

        :return: positive or negative amount in sat (encodes
            the decrease/increase in the local balance)
        """
        # both parties need to maintain a channel reserve of 1%
        # according to BOLT 2
        channel_reserve = int(0.01 * unbalanced_channel_info['capacity'])

        if unbalancedness_target:
            # a commit fee needs to be only respected by the channel initiator
            commit_fee = 0 if not unbalanced_channel_info['initiator'] \
                else unbalanced_channel_info['commit_fee']

            # first naively calculate the local balance change to
            # fulfill the requested target
            local_balance_target = int(
                unbalanced_channel_info['capacity'] * 0.5 *
                (-unbalancedness_target + 1.0) - commit_fee)
            local_balance_change = local_balance_target - \
                unbalanced_channel_info['local_balance']

            # TODO: clarify exact definitions of dust and htlc_cost
            # related: https://github.com/lightningnetwork/lnd/issues/1076
            # https://github.com/lightningnetwork/lightning-rfc/blob/master/03-transactions.md#fees

            dust = 700
            htlc_weight = 172
            number_htlcs = 2
            htlc_cost = int(
                number_htlcs * htlc_weight *
                unbalanced_channel_info['fee_per_kw'] / 1000)
            logger.debug(f">>> Assuming a dust limit of {dust} sat and an "
                         f"HTLC cost of {htlc_cost} sat.")

            # we can only send the local balance less the channel reserve
            # (if above the dust limit), less the cost to enforce the HTLC
            can_send = max(0, unbalanced_channel_info['local_balance']
                           - max(dust, channel_reserve) - htlc_cost - 1)

            # we can only receive the remote balance less the channel reserve
            # (if above the dust limit)
            can_receive = max(0, unbalanced_channel_info['remote_balance']
                              - max(dust, channel_reserve) - 1)

            logger.debug(f">>> Channel can send {can_send} sat and receive "
                         f"{can_receive} sat.")

            # check that we respect and enforce the channel reserve
            if (local_balance_change > 0 and
                    abs(local_balance_change)) > can_receive:
                local_balance_change = can_receive
            if (local_balance_change < 0 and
                    abs(local_balance_change)) > can_send:
                local_balance_change = -can_send

            amt_target_original = int(local_balance_change)
        else:
            # use the already calculated optimal amount for 50:50 balancedness
            amt_target_original = unbalanced_channel_info['amt_to_balanced']

        return amt_target_original

    def _node_is_multiple_connected(self, pub_key: str) -> bool:
        """
        Checks if the node is connected to us via several channels.

        :param pub_key: node public key

        :return: true if number of channels to the node is larger than 1
        """
        n_channels = 0
        for pk, chan_info in self.channel_list.items():
            if chan_info['remote_pubkey'] == pub_key:
                n_channels += 1
        if n_channels > 1:
            return True
        else:
            return False

    def rebalance(self, channel_id: int, dry=False, chunksize=1.0, target=Optional[float],
                  allow_unbalancing=False, strategy=Optional[str]):
        """
        Automatically rebalances a selected channel with a fee cap of
        self.budget_sat and self.max_effective_fee_rate.

        Rebalancing candidates are selected among all channels which are
        unbalanced in the other direction.
        Uses :func:`self.rebalance_two_channels` for rebalancing a pairs
        of channels.

        At the moment, rebalancing channels are tried one at a time,
        so it is not yet optimized for the lowest possible fees.

        The chunksize allows for partitioning of the individual rebalancing
        attempts into smaller pieces than would maximally possible. The smaller
        the chunksize the higher is the success rate, but the rebalancing
        cost increases.

        :param channel_id:
        :param dry: if set, then there's a dry run
        :param chunksize: a number between 0 and 1
        :param target: specifies unbalancedness after rebalancing in [-1, 1]
        :param allow_unbalancing: allows counterparty channels
            to get a little bit unbalanced
        :param strategy: lets you select a strategy for rebalancing order

        :return: fees in msat paid for rebalancing

        :raises MultichannelInboundRebalanceFailure: can't rebalance channels
            with a node we are mutiply connected
        :raises NoRebalanceCandidates: there are no counterparty rebalance
            candidates
        :raises RebalanceCandidatesExhausted: no more conterparty rebalance
            candidates
        :raises TooExpensive: the rebalance became too expensive
        """
        if not (0.0 <= chunksize <= 1.0):
            raise ValueError("Chunk size must be between 0.0 and 1.0.")
        if not (-1.0 <= target <= 1.0):
            raise ValueError("Target must be between -1.0 and 1.0.")

        logger.info(f">>> Trying to rebalance channel {channel_id} "
                    f"with a max rate of {self.max_effective_fee_rate} "
                    f"and a max fee of {self.budget_sat} sat.")

        if dry:
            logger.info(f">>> This is a dry run, nothing to fear.")

        # get a fresh channel list
        self.channel_list = self.node.get_unbalanced_channels()
        unbalanced_channel_info = self.channel_list[channel_id]

        # if a target is given and it is set close to -1 or 1,
        # then we need to think about the channel reserve
        initial_local_balance_change = self._maximal_local_balance_change(
            target, unbalanced_channel_info)

        if initial_local_balance_change == 0:
            logger.info(f"Channel already balanced.")
            return 0

        # copy the original target
        local_balance_change_left = initial_local_balance_change

        # if chunksize is set, rebalance in portions of chunked_amount
        chunked_amount = int(initial_local_balance_change * chunksize)
        logger.info(f">>> Chunk size is set to {chunksize}. "
                    f"Results in chunksize of {chunked_amount} sat.")

        # determine rebalance direction 1: receive, -1: send (of channel_id)
        rebalance_direction = math.copysign(1, initial_local_balance_change)

        logger.info(
            f">>> The channel status before rebalancing is "
            f"lb:{unbalanced_channel_info['local_balance']} sat "
            f"rb:{unbalanced_channel_info['remote_balance']} sat "
            f"cap:{unbalanced_channel_info['capacity']} sat.")
        logger.debug(
            f">>> Commit fee {unbalanced_channel_info['commit_fee']} "
            f"sat. We opened channel: {unbalanced_channel_info['initiator']}. "
            f"Channel reserve: "
            f"{int(unbalanced_channel_info['capacity'] * 0.01)} sat.")
        logger.debug(
            f">>> The change in local balance towards the requested "
            f"target (ub={target if target else 0.0:3.2f})"
            f" is {initial_local_balance_change} sat.")

        # a commit fee is only accounted for, if we opened the channel
        commit_fee = 0
        if unbalanced_channel_info['initiator']:
            commit_fee = unbalanced_channel_info['commit_fee']

        expected_target = -2 * ((
            unbalanced_channel_info['local_balance'] +
            initial_local_balance_change + commit_fee) /
            float(unbalanced_channel_info['capacity'])) + 1

        logger.info(
            f">>> Trying to change the local balance by "
            f"{initial_local_balance_change} sat.\n"
            f"    The expected unbalancedness target is "
            f"{expected_target:3.2f} (respecting channel reserve), "
            f"requested target is {0 if not target else target:3.2f}.")

        node_is_multiple_connected = self._node_is_multiple_connected(
            unbalanced_channel_info['remote_pubkey'])

        if initial_local_balance_change > 0 and node_is_multiple_connected:
            # TODO: this might be too strict, figure out exact behavior
            raise MultichannelInboundRebalanceFailure(
                "Receiving-rebalancing of multiple "
                "connected node channel not supported.\n"
                "The reason is that the last hop "
                "(channel) can't be controlled by us.\n"
                "See https://github.com/lightningnetwork/"
                "lnd/issues/2966 and \n"
                "https://github.com/lightningnetwork/"
                "lightning-rfc/blob/master/"
                "04-onion-routing.md#non-strict-forwarding.\n"
                "Tip: keep only the best channel to "
                "the node and then rebalance.")

        rebalance_candidates = self._get_rebalance_candidates(
            channel_id, local_balance_change_left,
            allow_unbalancing=allow_unbalancing, strategy=strategy)
        if len(rebalance_candidates) == 0:
            raise NoRebalanceCandidates(
                "Didn't find counterparty rebalance candidates.")

        logger.info(
            f">>> There are {len(rebalance_candidates)} channels with which "
            f"we can rebalance (look at logs).")

        self._print_rebalance_candidates(rebalance_candidates)

        logger.info(
            f">>> We will try to rebalance with them one after another.")
        logger.info(
            f">>> NOTE: only individual rebalance requests "
            f"are optimized for fees:\n"
            f"    this means that there can be rebalances with "
            f"less fees afterwards,\n"
            f"    so take a look at the dry runs first, "
            f"i.e. without the --reckless flag,\n"
            f"    and set --max-fee-sat and --max-fee-rate accordingly.\n"
            f"    You may also specify a rebalancing strategy "
            f"by the --strategy flag.")
        logger.info(
            f">>> Rebalancing can take some time. Please be patient!\n")

        total_fees_msat = 0

        # loop over the rebalancing candidates
        for c in rebalance_candidates:

            if total_fees_msat >= self.budget_sat * 1000:
                raise TooExpensive(
                    f"Fee budget exhausted. "
                    f"Total fees {total_fees_msat / 1000:.3f} sat.")

            source_channel, target_channel = \
                self._get_source_and_target_channels(
                    channel_id, c['chan_id'], rebalance_direction)

            # counterparty channel affords less than total rebalance amount
            if abs(local_balance_change_left) > abs(c['amt_affordable']):
                sign = math.copysign(1, c['amt_affordable'])
                minimal_amount = sign * min(
                    abs(chunked_amount), abs(c['amt_affordable']))
                amt = -int(rebalance_direction * minimal_amount)
            # counterparty channel affords more than total rebalance amount
            else:
                sign = math.copysign(1, local_balance_change_left)
                minimal_amount = sign * min(
                    abs(local_balance_change_left), abs(chunked_amount))
                amt = int(rebalance_direction * minimal_amount)
            # amt must be always positive
            if amt < 0:
                raise RebalanceCandidatesExhausted(
                    f"Amount should not be negative! amt:{amt} sat")

            logger.info(
                f"-------- Rebalance from {source_channel} to {target_channel}"
                f" with {amt} sat --------")
            logger.info(
                f"Need to still change the local balance by "
                f"{local_balance_change_left} sat to reach the goal "
                f"of {initial_local_balance_change} sat. "
                f"Fees paid up to now: {total_fees_msat / 1000:.3f} sat.")

            # for each rebalance attempt, get a new invoice
            invoice = self.node.get_invoice(
                amt_msat=amt*1000,
                memo=f"lndmanage: Rebalance of channel {channel_id}.")
            payment_hash, payment_address = invoice.r_hash, invoice.payment_addr
            # attempt the rebalance
            try:
                # be up to date with the blockheight, otherwise could lead
                # to cltv errors
                self.node.update_blockheight()
                total_fees_msat += self.rebalance_two_channels(
                    source_channel, target_channel, amt, payment_hash, payment_address,
                    self.budget_sat, dry=dry)
                local_balance_change_left -= int(rebalance_direction * amt)

                relative_amt_to_go = (local_balance_change_left /
                                      initial_local_balance_change)

                # perfect rebalancing is not always possible,
                # so terminate if at least 90% of amount was reached
                if relative_amt_to_go <= 0.10:
                    logger.info(
                        f"Goal is reached. Rebalancing done. "
                        f"Total fees were {total_fees_msat / 1000:.3f} sat.")
                    return total_fees_msat
            except NoRoute:
                logger.error(
                    "There was no reliable route with enough capacity.\n")
            except DryRun:
                logger.info(
                    "Would have tried this route now, but it was a dry run.\n")
            except TooExpensive:
                logger.error(
                    "Too expensive, check --max-fee-rate and --max-fee-sat.\n")
            except RebalanceFailure:
                logger.error(
                    "Failed to rebalance with this channel.\n")

        raise RebalanceCandidatesExhausted(
            "There are no further counterparty rebalance channel candidates "
            "for this channel.\n")

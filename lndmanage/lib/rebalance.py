"""Module for channel rebalancing."""
import logging
import math
from typing import TYPE_CHECKING, Optional, Dict
import time

from lndmanage.lib.rating import node_badness
from lndmanage.lib.routing import Router
from lndmanage.lib import exceptions
from lndmanage.lib.forwardings import get_channel_properties
from lndmanage.lib.exceptions import (
    DryRun,
    NoRebalanceCandidates,
    NoRoute,
    NotEconomic,
    PaymentTimeOut,
    RebalanceFailure,
    RebalancingTrialsExhausted,
    TooExpensive,
)
from lndmanage.lib.ln_utilities import unbalancedness_to_local_balance, parse_nodeid_channelid
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFAULT_MAX_FEE_RATE = 0.001000
DEFAULT_AMOUNT_SAT = 100000
RESERVED_REBALANCE_FEE_RATE_MILLI_MSAT = 50  # a buffer for the fee rate a rebalance route can cost
FORWARDING_STATS_DAYS = 30  # how many days will be taken into account when determining the rebalance direction
MIN_REBALANCE_AMOUNT_SAT = 20_000
MAX_UNBALANCEDNESS_FOR_CANDIDATES = 0.2  # sending rebalance candidates will not have an unbalancedness higher than this


class Rebalancer(object):
    """Implements methods for rebalancing."""

    def __init__(self, node: 'LndNode', max_effective_fee_rate: float, budget_sat: int, force=False):
        """
        :param node: node instance
        :param max_effective_fee_rate: maximum effective fee rate (base_fee + fee_rate * amt)/amt paid
        :param budget_sat: maximal rebalancing budget
        :param force: allow uneconomic routes / rebalance candidates
        """
        self.node = node
        self.channels = {}
        self.router = Router(self.node)
        # we don't want to route over our node, so blacklist it:
        self.node.network.channel_rater.blacklist_add_node(self.node.pub_key)
        self.max_effective_fee_rate = max_effective_fee_rate
        self.budget_sat = budget_sat
        self.force = force

    def _rebalance(
            self,
            send_channels: Dict[int, dict],
            receive_channels: Dict[int, dict],
            amt_sat: int,
            payment_hash: bytes,
            payment_address: bytes,
            budget_sat: int,
            dry=False,
    ) -> int:
        """Rebalances liquidity from send_channels to receive_channels with an amount of
        amt_sat.

        A prior created payment_hash has to be given. The budget_sat sets
        the maxmimum fees in sat that will be paid. A dry run can be done.

        :param send_channels: channels for sending with info
        :param receive_channels: channels for receiving with info
        :param amt_sat: amount to be sent in sat
        :param payment_hash: payment hash
        :param payment_address: payment secret
        :param budget_sat: budget for the rebalance in sat
        :param dry: specifies, if it is a dry run

        :return: total fees for the whole rebalance in msat

        :raises TemporarayChannelFailure: no liquidity along path
        :raises UnknownNextPeer: a routing node didn't where to forward
        :raises DuplicateRoute: the same route was already tried
        :raises NoRoute: no route was found from source to destination
        :raises TooExpensive: the circular payment would exceed the fee limits
        :raises PaymentTimeOut: the payment timed out
        :raises DryRun: attempt was just a dry run
        :raises NotEconomic: we would effectively loose money due to not enough expected
            earnings in the future
        """
        # be up to date with the blockheight, otherwise could lead to cltv errors
        self.node.update_blockheight()
        amt_msat = amt_sat * 1000

        count = 0
        while True:
            start_time = time.time()
            count += 1
            if count > settings.REBALANCING_TRIALS:
                raise RebalancingTrialsExhausted
            logger.info(f">>> Trying to rebalance with {amt_sat} sat (attempt number {count}).")

            route = self.router.get_route(send_channels, receive_channels, amt_msat)
            if not route:
                raise NoRoute

            effective_fee_rate = route.total_fee_msat / route.total_amt_msat
            logger.info(
                f"  > Route summary: amount: {(route.total_amt_msat - route.total_fee_msat) / 1000:3.3f} "
                f"sat, total fee: {route.total_fee_msat / 1000:3.3f} sat, "
                f"fee rate: {effective_fee_rate:1.6f}, "
                f"number of hops: {len(route.channel_hops)}")
            logger.debug(f"   Channel hops: {route.channel_hops}")

            # check if route makes sense
            illiquid_channel_id = route.channel_hops[-1]
            illiquid_channel = self.channels[illiquid_channel_id]
            liquid_channel_id = route.channel_hops[0]
            liquid_channel = self.channels[liquid_channel_id]
            assert illiquid_channel_id in list(receive_channels.keys()), "receiving channel should be in receive list"
            assert liquid_channel_id in list(send_channels.keys()), "sending channel should be in send list"

            # check economics
            fee_rate_margin = (illiquid_channel['local_fee_rate'] - liquid_channel['local_fee_rate']) / 1_000_000
            logger.info(f"  > Expected gain: {(fee_rate_margin - effective_fee_rate) * amt_sat:3.3f} sat")
            if (effective_fee_rate > fee_rate_margin) and not self.force:
                # TODO: We could look for the hop that charges the highest fee
                #  and blacklist it, to ignore it in the next path.
                pass

            if effective_fee_rate > self.max_effective_fee_rate:
                raise TooExpensive(f"Route is too expensive (rate too high). Rate: {effective_fee_rate:.6f}, "
                                   f"requested max rate: {self.max_effective_fee_rate:.6f}")

            if route.total_fee_msat > budget_sat * 1000:
                raise TooExpensive(f"Route is too expensive (budget exhausted). Total fee of route: "
                                   f"{route.total_fee_msat / 1000:.3f} sat, budget: {budget_sat:.3f} sat")

            def report_success_up_to_failed_hop(failed_hop_index: Optional[int]):
                """Rates the route."""
                end_time = time.time()
                elapsed_time = end_time - start_time
                logger.debug(f"  > time elapsed: {elapsed_time:3.1f} s")

                success_path_length = failed_hop_index + 1 if failed_hop_index else len(route.hops)
                for hop, channel in enumerate(route.hops):
                    source_node = route.node_hops[hop]
                    target_node = route.node_hops[hop + 1]
                    self.node.network.liquidity_hints.update_elapsed_time(source_node, elapsed_time / success_path_length)
                    if failed_hop_index and hop == failed_hop_index:
                        break
                    self.node.network.liquidity_hints.update_can_send(source_node, target_node, channel['chan_id'], amt_msat)

                # symmetrically penalize a route about the error source if it failed
                if failed_hop_index:
                    for node_number, node in enumerate(route.node_hops):
                        badness = node_badness(node_number, failed_hop_index)
                        self.node.network.liquidity_hints.update_badness_hint(node, badness)

            if not dry:
                try:
                    result = self.node.send_to_route(route, payment_hash, payment_address)
                except PaymentTimeOut:
                    raise PaymentTimeOut
                # TODO: check whether the failure source is correctly attributed
                except exceptions.TemporaryChannelFailure as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.TemporaryNodeFailure as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.UnknownNextPeer as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.ChannelDisabled as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.FeeInsufficient as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.IncorrectCLTVExpiry as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                except exceptions.In as e:
                    failed_hop = int(e.payment.failure.failure_source_index)
                else:
                    logger.debug(f"Preimage: {result.preimage.hex()}")
                    logger.info("Success!\n")
                    report_success_up_to_failed_hop(failed_hop_index=None)
                    self.node.network.save_liquidty_hints()
                    return route.total_fee_msat

                if failed_hop:
                    failed_channel_id = route.hops[failed_hop]['chan_id']
                    failed_source = route.node_hops[failed_hop]
                    failed_target = route.node_hops[failed_hop + 1]

                    if failed_channel_id in [send_channels, receive_channels]:
                        raise RebalanceFailure(
                            f"Own channel failed. Something is wrong. "
                            f"This is likely due to a wrong accounting "
                            f"for the channel reserve and will be fixed "
                            f"in the future. "
                            f"Try with smaller absolute target. "
                            f"Failing channel: {failed_channel_id}")

                    # determine the nodes involved in the channel
                    logger.info(f"  > Failed: hop: {failed_hop + 1}, channel: {failed_channel_id}")
                    logger.info(f"  > Could not reach {failed_target} ({self.node.network.node_alias(failed_target)})\n")
                    logger.debug(f"  > Node hops {route.node_hops}")
                    logger.debug(f"  > Channel hops {route.channel_hops}")

                    # report that channel could not route the amount to liquidity hints
                    self.node.network.liquidity_hints.update_cannot_send(
                        failed_source, failed_target, failed_channel_id, amt_msat)

                    # report all the previous hops that they could route the amount
                    report_success_up_to_failed_hop(failed_hop)
                    self.node.network.save_liquidty_hints()
            else:
                raise DryRun

    def _get_rebalance_candidates(
            self,
            channel_id: int,
            channel_fee_rate_milli_msat: int,
            local_balance_change: int,
    ) -> Dict:
        """
        Determines channels, which can be used to rebalance a channel.

        If the local_balance_change is negative, the local balance of the to
        be balanced channel is tried to be reduced. This method determines
        channels with which we can rebalance by considering channels which have enough
        funds and for which rebalancing makes economically sense based on fee rates.

        :param channel_id: the channel id of the to be rebalanced channel
        :param channel_fee_rate_milli_msat: the local fee rate of the to be rebalanced
            channel
        :param local_balance_change: amount by which the local balance of
            channel should change in sat

        :return: rebalance candidates with information
        """
        # update the channel list to reflect up-to-date balances
        self.channels = self.node.get_unbalanced_channels()

        # need to make sure we don't rebalance with the same channel or other channels
        # of the same node
        map_channel_id_node_id = self.node.channel_id_to_node_id()
        rebalance_node_id = map_channel_id_node_id[channel_id]
        removed_channels = [cid for cid, nid in map_channel_id_node_id.items() if nid == rebalance_node_id]
        rebalance_candidates = {
            k: c for k, c in self.channels.items() if k not in removed_channels}

        # filter channels, which can't receive/send the amount
        candidates_send = True if local_balance_change > 0 else False
        rebalance_candidates_with_funds = {}
        for k, c in rebalance_candidates.items():
            if candidates_send:
                maximal_can_send = self._maximal_local_balance_change(False, c)
                if maximal_can_send > abs(local_balance_change) and \
                        c['unbalancedness'] < MAX_UNBALANCEDNESS_FOR_CANDIDATES:
                    rebalance_candidates_with_funds[k] = c
            else:
                maximal_can_receive = self._maximal_local_balance_change(True, c)
                if maximal_can_receive > abs(local_balance_change) and \
                        c['unbalancedness'] > -MAX_UNBALANCEDNESS_FOR_CANDIDATES:
                    rebalance_candidates_with_funds[k] = c

        # We only include rebalance candidates for which it makes economically sense to
        # rebalance. This is determined by the difference in fee rates:
        # For an increase in the local balance of a channel, we need to decrease the
        # local balance in another one:
        #   the fee rate margin is:
        #   fee_rate[rebalance_channel] - fee_rate[candidate_channel],
        #   it always needs to be positive at least
        rebalance_candidates_filtered = {}
        for k, c in rebalance_candidates_with_funds.items():
            if not self.force:  # we allow only economic candidates
                if local_balance_change < 0:  # we take liquidity out of the channel
                    fee_rate_margin = c['local_fee_rate'] - channel_fee_rate_milli_msat
                else:  # putting liquidity into the channel
                    fee_rate_margin = channel_fee_rate_milli_msat - c['local_fee_rate']
                # We enforce a mimimum amount of an acceptable fee rate,
                # because we need to also pay for rebalancing.
                if fee_rate_margin > RESERVED_REBALANCE_FEE_RATE_MILLI_MSAT:
                    c['fee_rate_margin'] = fee_rate_margin / 1_000_000
                    rebalance_candidates_filtered[k] = c
            else:  # otherwise, we can afford very high fee rates
                c['fee_rate_margin'] = float('inf')
                rebalance_candidates_filtered[k] = c
        return rebalance_candidates_filtered

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
    def _debug_rebalance_candidates(rebalance_candidates: Dict[int, dict]):
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
            "lbf: local base fee [msat]\n"
            "lfr: local fee rate\n"
            "frm: fee rate margin\n"
            "a: alias"
        )

        logger.debug(f"-------- Candidates in order of rebalance attempts "
                     f"--------")
        for c in rebalance_candidates.values():
            logger.debug(
                f"cid:{c['chan_id']} "
                f"ub:{c['unbalancedness']: 4.2f} "
                f"l:{c['local_balance']: 9d} "
                f"r:{c['remote_balance']: 9d} "
                f"lbf:{c['local_base_fee']: 6d} "
                f"lfr:{c['local_fee_rate']/1E6: 1.6f} "
                f"fra:{c.get('fee_rate_margin'): 1.6f} "
                f"a:{c['alias']}")

    @staticmethod
    def _maximal_local_balance_change(
            increase_local_balance: bool,
            unbalanced_channel_info: dict
    ) -> int:
        """Finds the amount to maximally send/receive via the channel."""
        local_balance = unbalanced_channel_info['local_balance']
        remote_balance = unbalanced_channel_info['remote_balance']
        remote_channel_reserve = unbalanced_channel_info['remote_chan_reserve_sat']
        local_channel_reserve = unbalanced_channel_info['local_chan_reserve_sat']

        if increase_local_balance:  # we want to add funds to the channel
            local_balance_change = remote_balance
            local_balance_change -= remote_channel_reserve
        else:  # we want to decrease funds
            local_balance_change = local_balance
            local_balance_change -= local_channel_reserve

        # the local balance already reflects commitment transaction fees
        # in principle we should account for the HTLC output here
        local_balance_change -= 172 * unbalanced_channel_info['fee_per_kw'] / 1000

        # TODO: buffer for all the rest of costs which is why
        #  local_balance_change can be negative
        return max(0, int(local_balance_change))

    def _node_is_multiple_connected(self, pub_key: str) -> bool:
        """Checks if the node is connected to us via several channels.

        :param pub_key: node public key

        :return: true if number of channels to the node is larger than 1
        """
        n_channels = 0
        for pk, chan_info in self.channels.items():
            if chan_info['remote_pubkey'] == pub_key:
                n_channels += 1
        if n_channels > 1:
            return True
        else:
            return False

    def rebalance(
            self,
            node_id_channel_id: str,
            dry=False,
            target: float = None,
            amount_sat: int = None,
    ) -> int:
        """Automatically rebalances a selected channel with a fee cap of
        self.budget_sat and self.max_effective_fee_rate.

        Rebalancing candidates are selected among all channels that support the
        rebalancing operation (liquidity-wise), which are economically viable
        (controlled through self.force) determined by fees rates of
        counterparty channels.

        The rebalancing operation is carried out in these steps:
        0. determine balancing amount, determine rebalance direction
        1. determine counterparty channels for the balancing amount
        2. try to rebalance with the cheapest route (taking into account different metrics including fees)
        3. if it doesn't work for several attempts, go to 1. with a reduced amount

        :param node_id_channel_id: the id of the peer or channel to be rebalanced
        :param dry: if set, it's a dry run
        :param target: specifies unbalancedness after rebalancing in [-1, 1]
        :param amount_sat: rebalance amount (target takes precedence)

        :return: fees in msat paid for rebalancing

        :raises MultichannelInboundRebalanceFailure: can't rebalance channels
            with a node we are mutiply connected
        :raises NoRebalanceCandidates: there are no counterparty rebalance
            candidates
        :raises RebalanceCandidatesExhausted: no more conterparty rebalance
            candidates
        :raises TooExpensive: the rebalance became too expensive
        """
        if target and not (-1.0 <= target <= 1.0):
            raise ValueError("Target must be between -1.0 and 1.0.")

        # convert the node id to a channel id if possible
        self.channels = self.node.get_unbalanced_channels()
        channel_id, node_id = parse_nodeid_channelid(node_id_channel_id)
        if node_id:
            node_id_to_channel_ids_map = self.node.node_id_to_channel_ids()
            for nid, cs in node_id_to_channel_ids_map.items():
                if nid == node_id:
                    if len(cs) > 1:
                        raise ValueError("Several channels correspond to node id, please specify channel id.")
                    channel_id = cs[0]
        try:
            unbalanced_channel_info = self.channels[channel_id]
        except KeyError:
            raise RebalanceFailure("Channel not known or inactive.")

        # 0. determine the amount we want to send/receive on the channel
        if target is not None:
            if target < unbalanced_channel_info['unbalancedness']:
                increase_local_balance = True
            else:
                increase_local_balance = False

            maximal_abs_local_balance_change = self._maximal_local_balance_change(
                increase_local_balance, unbalanced_channel_info)
            target_local_balance, _ = unbalancedness_to_local_balance(
                target,
                unbalanced_channel_info['capacity'],
                unbalanced_channel_info['commit_fee'],
                unbalanced_channel_info['initiator']
            )
            abs_local_balance_change = abs(target_local_balance - unbalanced_channel_info['local_balance'])
            initial_local_balance_change = min(abs_local_balance_change, maximal_abs_local_balance_change)
            # encode the sign to send (< 0) or receive (> 0)
            initial_local_balance_change *= 1 if increase_local_balance else -1

            if abs(initial_local_balance_change) <= 10_000:
                logger.info(f"Channel already balanced.")
                return 0
        elif not amount_sat:  # if no target is given, we enforce some default amount
            now_sec = time.time()
            then_sec = now_sec - FORWARDING_STATS_DAYS * 24 * 3600
            forwarding_properties = get_channel_properties(self.node, then_sec, now_sec)
            channel_properties = forwarding_properties.get(channel_id)
            fees_in = channel_properties['fees_in']
            fees_out = channel_properties['fees_out']
            ub = unbalanced_channel_info['unbalancedness']
            flow = channel_properties['flow_direction']

            if abs(ub) > 0.95:  # there's no other option
                initial_local_balance_change = int(math.copysign(1, ub) * DEFAULT_AMOUNT_SAT)
                logger.debug("Default amount due to strong unbalancedness.")
            elif fees_in or fees_out:  # based on type of earnings
                if fees_out > fees_in:  # then we want to increase balance in channel
                    initial_local_balance_change = DEFAULT_AMOUNT_SAT
                else:
                    initial_local_balance_change = -DEFAULT_AMOUNT_SAT
                logger.debug("Default amount due to fees.")
            elif not math.isnan(flow):  # counter the flow, probably not executed
                initial_local_balance_change = int(math.copysign(1, flow) * DEFAULT_AMOUNT_SAT)
                logger.debug("Default amount due to flow.")
            else:  # fall back to unbalancedness
                initial_local_balance_change = int(math.copysign(1, ub) * DEFAULT_AMOUNT_SAT)
                logger.debug("Default amount due to unbalancedness.")
        else:  # based on manual amount, checking bounds
            increase_local_balance = True if amount_sat > 0 else False
            maximal_change = self._maximal_local_balance_change(
                increase_local_balance=increase_local_balance,
                unbalanced_channel_info=unbalanced_channel_info
            )
            if abs(amount_sat) > maximal_change:
                raise ValueError(
                    f"Channel cannot {'receive' if increase_local_balance else 'send'} "
                    f"(maximal value: {int(math.copysign(1, amount_sat) * maximal_change)} sat)."
                    f" lb: {unbalanced_channel_info['local_balance']} sat"
                    f" rb: {unbalanced_channel_info['remote_balance']} sat")
            initial_local_balance_change = amount_sat

        # determine budget and fee rate from local balance change:
        # budget fee_rate  result
        #    x      0      set fee rate
        #    0      x      set budget
        #    x      x      max(budget, budget from fee rate): set fee rate and budget
        #    0      0      set defaults from a fee rate
        net_change = abs(initial_local_balance_change)
        if self.budget_sat and not self.max_effective_fee_rate:
            self.max_effective_fee_rate = self.budget_sat / net_change
        elif not self.budget_sat and self.max_effective_fee_rate:
            self.budget_sat = int(self.max_effective_fee_rate * net_change)
        elif self.budget_sat and self.max_effective_fee_rate:
            budget_from_fee_rate = int(net_change * self.max_effective_fee_rate)
            budget = max(budget_from_fee_rate, self.budget_sat)
            self.budget_sat = budget
            self.max_effective_fee_rate = budget / net_change
        else:
            self.budget_sat = int(DEFAULT_MAX_FEE_RATE * net_change)
            self.max_effective_fee_rate = DEFAULT_MAX_FEE_RATE

        logger.info(f">>> Trying to rebalance channel {channel_id} "
                    f"with a max rate of {self.max_effective_fee_rate} "
                    f"and a max fee of {self.budget_sat} sat.")

        if dry:
            logger.info(f">>> This is a dry run, nothing to fear.")

        # copy the original target for bookkeeping
        local_balance_change_left = initial_local_balance_change

        logger.info(
            f">>> The channel status before rebalancing is "
            f"lb:{unbalanced_channel_info['local_balance']} sat "
            f"rb:{unbalanced_channel_info['remote_balance']} sat "
            f"cap:{unbalanced_channel_info['capacity']} sat.")
        logger.debug(
            f">>> Commit fee {unbalanced_channel_info['commit_fee']} "
            f"sat. We opened channel: {unbalanced_channel_info['initiator']}. "
            f"Channel reserve: "
            f"{unbalanced_channel_info['local_chan_reserve_sat']} sat.")
        logger.debug(
            f">>> The change in local balance towards the requested "
            f"target (ub={target if target else 0.0:3.2f})"
            f" is {initial_local_balance_change} sat.")

        # the fee rate that is charged by the to-be-rebalanced channel
        fee_rate_milli_msat = unbalanced_channel_info['local_fee_rate']

        # a channel reserve is only accounted for, if we opened the channel
        reserve_sat = 0 if not unbalanced_channel_info['initiator'] else unbalanced_channel_info['local_chan_reserve_sat']

        expected_target = -2 * ((
            unbalanced_channel_info['local_balance'] +
            initial_local_balance_change + reserve_sat) /
            float(unbalanced_channel_info['capacity'])) + 1

        info_str = f">>> Trying to change the local balance by " \
                   f"{initial_local_balance_change} sat.\n" \
                   f"    The expected unbalancedness target is " \
                   f"{expected_target:3.2f} (respecting channel reserve)"
        if target is not None:
            info_str += f", requested target is {target:3.2f}."
        logger.info(info_str)

        node_is_multiple_connected = self._node_is_multiple_connected(
            unbalanced_channel_info['remote_pubkey'])

        if initial_local_balance_change > 0 and node_is_multiple_connected:
            logger.info(
                ">>> Note: You try to send liquidity to a channel of a node you are\n"
                "    connected to with multiple channels. We cannot control over which\n"
                "    channel the funds are sent back to us due to so-called non-strict\n"
                "    forwarding, see:\n"
                "    https://github.com/lightningnetwork/lightning-rfc/blob/master/"
                "04-onion-routing.md#non-strict-forwarding.\n")

        logger.info(f">>> Rebalancing can take some time. Please be patient!\n")

        total_fees_paid_msat = 0
        # amount_sat is the amount we try to rebalance with, which is gradually reduced
        # to improve in rebalance success probability
        amount_sat = local_balance_change_left
        budget_sat = self.budget_sat

        # we try to rebalance with amount_sat until we reach the desired total local
        # balance change
        while abs(local_balance_change_left) >= 0:
            # 1. determine counterparty rebalance candidates
            rebalance_candidates = self._get_rebalance_candidates(
                channel_id, fee_rate_milli_msat, amount_sat)

            if len(rebalance_candidates) == 0:
                raise NoRebalanceCandidates(
                    "Didn't find counterparty rebalance candidates.")

            self._debug_rebalance_candidates(rebalance_candidates)

            if total_fees_paid_msat >= self.budget_sat * 1000:
                raise TooExpensive(
                    f"Fee budget exhausted. "
                    f"Total fees {total_fees_paid_msat / 1000:.3f} sat.")

            logger.info(
                f">>> Need to still change the local balance by "
                f"{local_balance_change_left} sat to reach the goal "
                f"of {initial_local_balance_change} sat. "
                f"Fees paid up to now: {total_fees_paid_msat / 1000:.3f} sat.")

            # for each rebalance amount, get a new invoice
            invoice = self.node.get_invoice(
                amt_msat=abs(amount_sat) * 1000,
                memo=f"lndmanage: Rebalance of channel {channel_id}.")
            payment_hash, payment_address = invoice.r_hash, invoice.payment_addr

            # set sending and receiving channels
            if amount_sat < 0:  # we send over the channel
                send_channels = {channel_id: unbalanced_channel_info}
                receive_channels = rebalance_candidates
            else:  # we receive over the channel
                send_channels = rebalance_candidates
                # TODO: we could also extend the receive channels to all channels with the node
                receive_channels = {channel_id: unbalanced_channel_info}

            # attempt the rebalance
            try:
                rebalance_fees_msat = self._rebalance(
                    send_channels, receive_channels, abs(amount_sat), payment_hash,
                    payment_address, budget_sat, dry=dry)

                # account for running costs / target
                budget_sat -= rebalance_fees_msat // 1000
                total_fees_paid_msat += rebalance_fees_msat
                local_balance_change_left -= amount_sat

                relative_amt_to_go = (local_balance_change_left /
                                      initial_local_balance_change)

                # if we succeeded to rebalance, we start again at a higher amount
                amount_sat = local_balance_change_left

                # perfect rebalancing is not always possible,
                # so terminate if at least 90% of amount was reached
                if relative_amt_to_go <= 0.10:
                    logger.info(
                        f"Goal is reached. Rebalancing done. "
                        f"Total fees were {total_fees_paid_msat / 1000:.3f} sat.")
                    return total_fees_paid_msat
            except DryRun:
                logger.info(
                    "Would have tried this route now, but it was a dry run.\n")
                return 0
            except (RebalancingTrialsExhausted, NoRoute, TooExpensive) as e:
                logger.info(e)
                # We have attempted to rebalance a lot of times or didn't find a route
                # with the current amount. To improve the success rate, we split the
                # amount.
                amount_sat //= 2
                if abs(amount_sat) < MIN_REBALANCE_AMOUNT_SAT:
                    raise RebalanceFailure(
                        "It is unlikely we can rebalance the channel. Attempts with "
                        "small amounts already failed.\n")
                logger.info(
                    f"Could not rebalance with this amount. Decreasing amount to "
                    f"{amount_sat} sat.\n"
                )

import math
from collections import defaultdict
from dataclasses import dataclass
import time
from typing import Set, Dict, Optional
from math import inf, log

import logging

from lndmanage.lib.data_types import NodeID, NodePair

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

BLACKLIST_DURATION = 3600  # how long (in seconds) a channel remains blacklisted
HINT_DURATION = 3600  # how long (in seconds) a liquidity hint remains valid
BADNESS_DECAY_ADJUSTMENT_SEC = 10 * 60  # adjustment interval for badness hints
BADNESS_DECAY_SEC = 24 * 3600  # exponential decay time for badness
TIME_EXPECTATION_ACCURACY = 0.2  # the relative error in estimating node reaction times
TIME_PENALTY_RATE = 0.000_010  # the default penalty for reaction time
TIME_NODE_IS_SLOW_SEC = 5  # the time a node is viewed as slow


@dataclass
class AmountHistory:
    amount: int = None  # msat
    timestamp: int = None

    def __bool__(self):
        return self.amount is not None and self.timestamp is not None

    def __gt__(self, other):
        return self and other and self.amount > other.amount

    def __lt__(self, other):
        return self and other and self.amount < other.amount

    def __str__(self):
        return str(self.amount)


class LiquidityHint:
    """Encodes the amounts that can and cannot be sent over the direction of a
    channel and whether the channel is blacklisted.

    A LiquidityHint is the value of a dict, which is keyed to node ids and the
    channel.
    """
    def __init__(self):
        # use "can_send_forward + can_send_backward < cannot_send_forward + cannot_send_backward" as a sanity check?
        self._can_send_forward = AmountHistory()
        self._cannot_send_forward = AmountHistory()
        self._can_send_backward = AmountHistory()
        self._cannot_send_backward = AmountHistory()
        self.blacklist_timestamp = 0
        self._inflight_htlcs_forward = 0
        self._inflight_htlcs_backward = 0

    def is_hint_invalid(self, timestamp: Optional[int]) -> bool:
        if timestamp is None:
            return True

        now = int(time.time())
        return now - timestamp > HINT_DURATION

    @property
    def can_send_forward(self) -> AmountHistory:
        if self.is_hint_invalid(self._can_send_forward.timestamp):
            return AmountHistory()
        return self._can_send_forward

    @can_send_forward.setter
    def can_send_forward(self, new_amount_history: AmountHistory):
        if new_amount_history < self._can_send_forward:
            # we don't want to record less significant info
            # (sendable amount is lower than known sendable amount):
            return
        self._can_send_forward = new_amount_history
        # we make a sanity check that sendable amount is lower than not sendable amount
        if self._can_send_forward > self._cannot_send_forward:
            self._cannot_send_forward = AmountHistory()

    @property
    def can_send_backward(self) -> AmountHistory:
        if self.is_hint_invalid(self._can_send_backward.timestamp):
            return AmountHistory()
        return self._can_send_backward

    @can_send_backward.setter
    def can_send_backward(self, new_amount_history: AmountHistory):
        if new_amount_history < self._can_send_backward:
            # don't overwrite with insignificant info
            return
        self._can_send_backward = new_amount_history
        # sanity check
        if self._can_send_backward > self._cannot_send_backward:
            self._cannot_send_backward = AmountHistory()

    @property
    def cannot_send_forward(self) -> AmountHistory:
        if self.is_hint_invalid(self._cannot_send_forward.timestamp):
            return AmountHistory()
        return self._cannot_send_forward

    @cannot_send_forward.setter
    def cannot_send_forward(self, new_amount_history: AmountHistory):
        if new_amount_history > self._cannot_send_forward:
            # don't overwrite with insignificant info
            return
        self._cannot_send_forward = new_amount_history
        # sanity check
        if self._can_send_forward > self._cannot_send_forward:
            self._can_send_forward = AmountHistory()

    @property
    def cannot_send_backward(self) -> AmountHistory:
        if self.is_hint_invalid(self._cannot_send_backward.timestamp):
            return AmountHistory()
        return self._cannot_send_backward

    @cannot_send_backward.setter
    def cannot_send_backward(self, new_amount_history: AmountHistory):
        if new_amount_history > self._cannot_send_backward:
            # don't overwrite with insignificant info
            return
        self._cannot_send_backward = new_amount_history
        # sanity check
        if self._can_send_backward > self._cannot_send_backward:
            self._can_send_backward = AmountHistory()

    def can_send(self, is_forward_direction: bool) -> AmountHistory:
        # make info invalid after some time?
        if is_forward_direction:
            return self.can_send_forward
        else:
            return self.can_send_backward

    def cannot_send(self, is_forward_direction: bool) -> AmountHistory:
        # make info invalid after some time?
        if is_forward_direction:
            return self.cannot_send_forward
        else:
            return self.cannot_send_backward

    def update_can_send(self, is_forward_direction: bool, amount: int,
                        timestamp: int = None):
        if not timestamp:
            timestamp = int(time.time())
        if is_forward_direction:
            self.can_send_forward = AmountHistory(amount, timestamp)
        else:
            self.can_send_backward = AmountHistory(amount, timestamp)

    def update_cannot_send(self, is_forward_direction: bool, amount: int,
                           timestamp: int = None):
        if not timestamp:
            timestamp = int(time.time())
        if is_forward_direction:
            self.cannot_send_forward = AmountHistory(amount, timestamp)
        else:
            self.cannot_send_backward = AmountHistory(amount, timestamp)

    def num_inflight_htlcs(self, is_forward_direction: bool) -> int:
        if is_forward_direction:
            return self._inflight_htlcs_forward
        else:
            return self._inflight_htlcs_backward

    def add_htlc(self, is_forward_direction: bool):
        if is_forward_direction:
            self._inflight_htlcs_forward += 1
        else:
            self._inflight_htlcs_backward += 1

    def remove_htlc(self, is_forward_direction: bool):
        if is_forward_direction:
            self._inflight_htlcs_forward = max(0, self._inflight_htlcs_forward - 1)
        else:
            self._inflight_htlcs_backward = max(0, self._inflight_htlcs_forward - 1)

    def __repr__(self):
        is_blacklisted = False if not self.blacklist_timestamp else int(time.time()) - self.blacklist_timestamp < BLACKLIST_DURATION
        return f"forward: can send: {self._can_send_forward} msat, cannot send: {self._cannot_send_forward} msat, htlcs: {self._inflight_htlcs_forward}\n" \
               f"backward: can send: {self._can_send_backward} msat, cannot send: {self._cannot_send_backward} msat, htlcs: {self._inflight_htlcs_backward}\n" \
               f"blacklisted: {is_blacklisted}"


class LiquidityHintMgr:
    """Implements liquidity hints for channels in the graph.

    This class can be used to update liquidity information about channels in the
    graph. Implements a penalty function for edge weighting in the pathfinding
    algorithm that favors channels which can route payments and penalizes
    channels that cannot.
    """
    # TODO: hints based on node pairs only (shadow channels, non-strict forwarding)?
    def __init__(self, source_node: str):
        self.source_node = source_node
        self._liquidity_hints: Dict[NodePair, LiquidityHint] = {}
        # could_not_route tracks node's failures to route
        self._could_not_route: Dict[NodeID, int] = defaultdict(int)
        # could_route tracks node's successes to route
        self._could_route: Dict[NodeID, int] = defaultdict(int)
        # elapsed_time is the cumulative time of payemtens up to the failing hop
        self._elapsed_time: Dict[NodeID, float] = defaultdict(float)
        # route_participations is the cumulative number of times a node was part of a
        # payment route
        self._route_participations: Dict[NodeID, int] = defaultdict(int)
        # badness_hints track the cumulative penalty (in units of a fee rate), which is
        # large for nodes that are close to failure sources along a path
        self._badness_hints: Dict[NodeID, float] = defaultdict(float)
        # badness hints have an exponential decay time of BADNESS_DECAY_SEC updated
        # every BADNESS_DECAY_ADJUSTMENT_SEC
        self._badness_timestamps: Dict[NodeID, float] = defaultdict(float)
        self.mc_sync_timestamp: int = 0

    @property
    def now(self):
        return time.time()

    def _get_hint(self, node_pair: NodePair) -> LiquidityHint:
        hint = self._liquidity_hints.get(node_pair)
        if not hint:
            hint = LiquidityHint()
            self._liquidity_hints[node_pair] = hint
        return hint

    def update_can_send(self, node_from: NodeID, node_to: NodeID, amount_msat: int,
                        timestamp: int = None):
        node_pair = NodePair((node_from, node_to))
        logger.debug(f"    report: can send {amount_msat // 1000} sat over channel {node_pair}")
        hint = self._get_hint(node_pair)
        hint.update_can_send(node_from > node_to, amount_msat, timestamp)
        self._could_route[node_from] += 1

    def update_cannot_send(self, node_from: NodeID, node_to: NodeID, amount: int,
                           timestamp: int = None):
        node_pair = NodePair((node_from, node_to))
        logger.debug(f"    report: cannot send {amount // 1000} sat over channel {node_pair}")
        hint = self._get_hint(node_pair)
        hint.update_cannot_send(node_from > node_to, amount, timestamp)
        self._could_not_route[node_from] += 1

    def update_badness_hint(self, node: NodeID, badness: float):
        self._badness_hints[node] += badness
        participations = self._route_participations[node]
        badness = self._badness_hints[node]
        average = badness / participations if participations else 0
        logger.debug(f"    report: update badness {badness} +=> badness (avg: {average}) (node: {node})")
        self._badness_timestamps[node] = time.time()
        self.update_route_participation(node)

    def update_route_participation(self, node: NodeID):
        self._route_participations[node] += 1
        logger.debug(f"    report: update route participation to {self._route_participations[node]} (node: {node})")

    def update_elapsed_time(self, node: NodeID, elapsed_time: float):
        self._elapsed_time[node] += elapsed_time
        nfwd = self._could_route[node]
        avg_time = self._elapsed_time[node] / nfwd if nfwd else 0
        logger.debug(f"    report: update elapsed time {elapsed_time} +=> {self._elapsed_time[node]} (avg: {avg_time}) (node: {node})")

    def add_htlc(self, node_from: NodeID, node_to: NodeID):
        node_pair = NodePair((node_from, node_to))
        hint = self._get_hint(node_pair)
        hint.add_htlc(node_from > node_to)

    def remove_htlc(self, node_from: NodeID, node_to: NodeID):
        node_pair = NodePair((node_from, node_to))
        hint = self._get_hint(node_pair)
        hint.remove_htlc(node_from > node_to)

    def penalty(self, node_from: NodeID, node_to: NodeID, capacity: int,
                amount_msat: int, fee_rate_milli_msat: int) -> float:
        """Gives a penalty when sending from node1 to node2 over channel_id with an
        amount in units of millisatoshi.

        The penalty depends on the can_send and cannot_send values that was
        possibly recorded in previous payment attempts.

        A channel that can send an amount is assigned a penalty of zero, a
        channel that cannot send an amount is assigned an infinite penalty.
        If the sending amount lies between can_send and cannot_send, there's
        uncertainty and we give a default penalty. The default penalty
        serves the function of giving a positive offset (the Dijkstra
        algorithm doesn't work with negative weights), from which we can discount
        from. There is a competition between low-fee channels and channels where
        we know with some certainty that they can support a payment. The penalty
        ultimately boils down to: how much more fees do we want to pay for
        certainty of payment success? This can be tuned via DEFAULT_PENALTY_BASE_MSAT
        and DEFAULT_PENALTY_PROPORTIONAL_MILLIONTH. A base _and_ relative penalty
        was chosen such that the penalty will be able to compete with the regular
        base and relative fees.
        """
        # we assume that our node can always route:
        if self.source_node in [node_from, ]:
            return 0
        # we only evaluate hints here, so use dict get (to not create many hints with self.get_hint)
        node_pair = NodePair((node_from, node_to))
        hint = self._liquidity_hints.get(node_pair)

        # fetch a hint if it exists
        can_send = None
        cannot_send = None
        if hint:
            can_send = hint.can_send(node_from > node_to).amount
            cannot_send = hint.cannot_send(node_from > node_to).amount

        # if the hint doesn't help us, we set defaults
        if can_send is None:
            can_send = 0
        if cannot_send is None:
            cannot_send = capacity * 1000

        if amount_msat >= cannot_send:
            return inf
        if amount_msat <= can_send:
            return 0

        log_penalty = - log((cannot_send - (amount_msat - can_send)) / cannot_send)
        # we give a base penalty if we haven't tried the channel yet
        penalty = fee_rate_milli_msat * amount_msat // 1_000_000

        return log_penalty * penalty

    def time_penalty(self, node, amount) -> float:
        """Gives a penalty for slow nodes in units of amount."""
        number_forwardings = self._could_route[node]
        elapsed_time = self._elapsed_time[node]
        avg_time = elapsed_time / number_forwardings if number_forwardings else 0
        estimated_error = avg_time / elapsed_time if elapsed_time else float('inf')
        if avg_time and estimated_error < TIME_EXPECTATION_ACCURACY:
            # if we are able to estimate the node reaction time accurately,
            # we penalize nodes that do have a reaction time larger than TIME_NODE_IS_SLOW
            return TIME_PENALTY_RATE * math.exp(avg_time / TIME_NODE_IS_SLOW_SEC - 1) * amount
        else:
            # otherwise give a default penalty
            return TIME_PENALTY_RATE * amount

    def badness_penalty(self, node_from: NodeID, amount: int) -> float:
        """The badness penalty indicates how close a node was to the failing hop of
        payment routes in units of a fee rate. This fee rate can accumulate and may
        lead to complete ignoring of the node, which is why we let the badness penalty
        decay in time to open up these payment paths again."""
        badness_timestamp = self._badness_timestamps[node_from]
        if badness_timestamp:
            time_delta = self.now - badness_timestamp
            # only adjust after some time has passed, we don't want to evaluate this
            # for every badness_penalty request
            if time_delta > BADNESS_DECAY_ADJUSTMENT_SEC:
                self._badness_hints[node_from] *= math.exp(-time_delta / BADNESS_DECAY_SEC)
        return amount * self._badness_hints[node_from]

    def add_to_blacklist(self, node_pair: NodePair):
        hint = self._get_hint(node_pair)
        now = int(time.time())
        hint.blacklist_timestamp = now

    def get_blacklist(self) -> Set[NodePair]:
        now = int(time.time())
        return set(k for k, v in self._liquidity_hints.items() if now - v.blacklist_timestamp < BLACKLIST_DURATION)

    def clear_blacklist(self):
        for k, v in self._liquidity_hints.items():
            v.blacklist_timestamp = 0

    def reset_liquidity_hints(self):
        for k, v in self._liquidity_hints.items():
            v._can_send_forward = AmountHistory()
            v._can_send_backward = AmountHistory()
            v._cannot_send_forward = AmountHistory()
            v._cannot_send_backward = AmountHistory()

    def __repr__(self):
        string = "liquidity hints:\n"
        if self._liquidity_hints:
            for k, v in self._liquidity_hints.items():
                string += f"{k}: {v}\n"
        return string

    def extend_with_mission_control(self, mc_pairs):
        logger.info("> Syncing mission control data.")
        for pair in mc_pairs:
            node_from = pair.node_from.hex()
            node_to = pair.node_to.hex()

            if pair.history.success_time:
                self.update_can_send(
                    node_from, node_to, pair.history.success_amt_msat,
                    pair.history.success_time,
                )

            if pair.history.fail_time:
                self.update_cannot_send(
                    node_from, node_to, pair.history.fail_amt_msat,
                    pair.history.fail_time,
                )
        self.mc_sync_timestamp = int(time.time())
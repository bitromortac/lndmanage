import math
from collections import defaultdict
import time
from typing import Set, Dict
from math import inf, log

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFAULT_PENALTY_BASE_MSAT = 1000  # how much base fee we apply for unknown sending capability of a channel
DEFAULT_PENALTY_PROPORTIONAL_MILLIONTH = 100  # how much relative fee we apply for unknown sending capability of a channel
BLACKLIST_DURATION = 3600  # how long (in seconds) a channel remains blacklisted
HINT_DURATION = 3600  # how long (in seconds) a liquidity hint remains valid
ATTEMPTS_TO_FAIL = 10  # if a node fails this often to forward a payment, we won't use it anymore
FAILURE_FEE_MSAT = 10_000


class ShortChannelID(int):
    pass


class NodeID(str):
    pass


class LiquidityHint:
    """Encodes the amounts that can and cannot be sent over the direction of a
    channel and whether the channel is blacklisted.

    A LiquidityHint is the value of a dict, which is keyed to node ids and the
    channel.
    """
    def __init__(self):
        # use "can_send_forward + can_send_backward < cannot_send_forward + cannot_send_backward" as a sanity check?
        self._can_send_forward = None
        self._cannot_send_forward = None
        self._can_send_backward = None
        self._cannot_send_backward = None
        self.blacklist_timestamp = 0
        self.hint_timestamp = 0
        self._inflight_htlcs_forward = 0
        self._inflight_htlcs_backward = 0

    def is_hint_invalid(self) -> bool:
        now = int(time.time())
        return now - self.hint_timestamp > HINT_DURATION

    @property
    def can_send_forward(self):
        return None if self.is_hint_invalid() else self._can_send_forward

    @can_send_forward.setter
    def can_send_forward(self, amount):
        # we don't want to record less significant info
        # (sendable amount is lower than known sendable amount):
        if self._can_send_forward and self._can_send_forward > amount:
            return
        self._can_send_forward = amount
        # we make a sanity check that sendable amount is lower than not sendable amount
        if self._cannot_send_forward and self._can_send_forward > self._cannot_send_forward:
            self._cannot_send_forward = None

    @property
    def can_send_backward(self):
        return None if self.is_hint_invalid() else self._can_send_backward

    @can_send_backward.setter
    def can_send_backward(self, amount):
        if self._can_send_backward and self._can_send_backward > amount:
            return
        self._can_send_backward = amount
        if self._cannot_send_backward and self._can_send_backward > self._cannot_send_backward:
            self._cannot_send_backward = None

    @property
    def cannot_send_forward(self):
        return None if self.is_hint_invalid() else self._cannot_send_forward

    @cannot_send_forward.setter
    def cannot_send_forward(self, amount):
        # we don't want to record less significant info
        # (not sendable amount is higher than known not sendable amount):
        if self._cannot_send_forward and self._cannot_send_forward < amount:
            return
        self._cannot_send_forward = amount
        if self._can_send_forward and self._can_send_forward > self._cannot_send_forward:
            self._can_send_forward = None
        # if we can't send over the channel, we should be able to send in the
        # reverse direction
        self.can_send_backward = amount

    @property
    def cannot_send_backward(self):
        return None if self.is_hint_invalid() else self._cannot_send_backward

    @cannot_send_backward.setter
    def cannot_send_backward(self, amount):
        if self._cannot_send_backward and self._cannot_send_backward < amount:
            return
        self._cannot_send_backward = amount
        if self._can_send_backward and self._can_send_backward > self._cannot_send_backward:
            self._can_send_backward = None
        self.can_send_forward = amount

    def can_send(self, is_forward_direction: bool):
        # make info invalid after some time?
        if is_forward_direction:
            return self.can_send_forward
        else:
            return self.can_send_backward

    def cannot_send(self, is_forward_direction: bool):
        # make info invalid after some time?
        if is_forward_direction:
            return self.cannot_send_forward
        else:
            return self.cannot_send_backward

    def update_can_send(self, is_forward_direction: bool, amount: int):
        self.hint_timestamp = int(time.time())
        if is_forward_direction:
            self.can_send_forward = amount
        else:
            self.can_send_backward = amount

    def update_cannot_send(self, is_forward_direction: bool, amount: int):
        self.hint_timestamp = int(time.time())
        if is_forward_direction:
            self.cannot_send_forward = amount
        else:
            self.cannot_send_backward = amount

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
        self._liquidity_hints: Dict[ShortChannelID, LiquidityHint] = {}
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

    def get_hint(self, channel_id: ShortChannelID) -> LiquidityHint:
        hint = self._liquidity_hints.get(channel_id)
        if not hint:
            hint = LiquidityHint()
            self._liquidity_hints[channel_id] = hint
        return hint

    def update_can_send(self, node_from: NodeID, node_to: NodeID, channel_id: ShortChannelID, amount_msat: int):
        logger.debug(f"    report: can send {amount_msat // 1000} sat over channel {channel_id}")
        hint = self.get_hint(channel_id)
        hint.update_can_send(node_from < node_to, amount_msat)
        self._could_route[node_from] += 1

    def update_cannot_send(self, node_from: NodeID, node_to: NodeID, channel_id: ShortChannelID, amount: int):
        logger.debug(f"    report: cannot send {amount // 1000} sat over channel {channel_id}")
        hint = self.get_hint(channel_id)
        hint.update_cannot_send(node_from < node_to, amount)
        self._could_not_route[node_from] += 1

    def update_badness_hint(self, node: NodeID, badness: float):
        self._badness_hints[node] += badness
        part = self._route_participations[node]
        badness = self._badness_hints[node]
        avg = badness / part if part else 0
        logger.debug(f"    report: update badness {badness} +=> badness (avg: {avg}) (node: {node})")
        self.update_route_participation(node)

    def update_route_participation(self, node: NodeID):
        self._route_participations[node] += 1
        logger.debug(f"    report: update route participation to {self._route_participations[node]} (node: {node})")

    def update_elapsed_time(self, node: NodeID, elapsed_time: float):
        self._elapsed_time[node] += elapsed_time
        nfwd = self._could_route[node]
        avg_time = self._elapsed_time[node] / nfwd if nfwd else 0
        logger.debug(f"    report: update elapsed time {elapsed_time} +=> {self._elapsed_time[node]} (avg: {avg_time}) (node: {node})")

    def add_htlc(self, node_from: NodeID, node_to: NodeID, channel_id: ShortChannelID):
        hint = self.get_hint(channel_id)
        hint.add_htlc(node_from < node_to)

    def remove_htlc(self, node_from: NodeID, node_to: NodeID, channel_id: ShortChannelID):
        hint = self.get_hint(channel_id)
        hint.remove_htlc(node_from < node_to)

    def penalty(self, node_from: NodeID, node_to: NodeID, edge: Dict, amount_msat: int, fee_rate_milli_msat: int) -> float:
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
        hint = self._liquidity_hints.get(edge['channel_id'])
        if not hint:
            can_send, cannot_send, num_inflight_htlcs = None, None, 0
        else:
            can_send = hint.can_send(node_from < node_to)
            cannot_send = hint.cannot_send(node_from < node_to)

        if can_send is None:
            can_send = 0
        if cannot_send is None:
            cannot_send = edge['capacity'] * 1000
        if amount_msat >= cannot_send:
            return inf
        if amount_msat <= can_send:
            return 0

        log_penalty = - log((cannot_send - (amount_msat - can_send)) / cannot_send)
        # we give a base penalty if we haven't tried the channel yet
        penalty = fee_rate_milli_msat * amount_msat // 1_000_000

        return log_penalty * penalty

    def time_penalty(self, node, amount) -> float:
        nfwd = self._could_route[node]
        elapsed_time = self._elapsed_time[node]
        avg_time = elapsed_time / nfwd if nfwd else 0
        estimated_error = avg_time / elapsed_time if elapsed_time else float('inf')
        # only give a time penalty if we have some certainty about it
        if avg_time and estimated_error < 0.2:
            return 0.000010 * math.exp(avg_time / 10 - 1) * amount
        else:
            return 0.000010 * amount

    def badness_penalty(self, node_from: NodeID, amount: int) -> float:
        """We blacklist a node if the attempts to fail are exhausted. Otherwise we just
        scale up the effective fee proportional to the failed attempts."""
        return amount * self._badness_hints[node_from]

    def add_to_blacklist(self, channel_id: ShortChannelID):
        hint = self.get_hint(channel_id)
        now = int(time.time())
        hint.blacklist_timestamp = now

    def get_blacklist(self) -> Set[ShortChannelID]:
        now = int(time.time())
        return set(k for k, v in self._liquidity_hints.items() if now - v.blacklist_timestamp < BLACKLIST_DURATION)

    def clear_blacklist(self):
        for k, v in self._liquidity_hints.items():
            v.blacklist_timestamp = 0

    def reset_liquidity_hints(self):
        for k, v in self._liquidity_hints.items():
            v.hint_timestamp = 0

    def __repr__(self):
        string = "liquidity hints:\n"
        if self._liquidity_hints:
            for k, v in self._liquidity_hints.items():
                string += f"{k}: {v}\n"
        return string

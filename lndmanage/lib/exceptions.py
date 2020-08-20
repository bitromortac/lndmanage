class RouteWithTooSmallCapacity(Exception):
    pass


class PaymentFailure(Exception):
    pass


class DryRun(Exception):
    pass


class PaymentTimeOut(Exception):
    pass


class TooExpensive(Exception):
    pass


class RebalanceFailure(Exception):
    pass


class RoutesExhausted(RebalanceFailure):
    pass


class RebalanceCandidatesExhausted(RebalanceFailure):
    pass


class NoRebalanceCandidates(RebalanceFailure):
    pass


class RebalancingTrialsExhausted(RebalanceFailure):
    pass


class MultichannelInboundRebalanceFailure(RebalanceFailure):
    pass


class PaymentError(Exception):
    pass


class PolicyError(PaymentError):
    pass


class InsufficientBandwidth(PaymentError):
    pass


class NoRoute(Exception):
    pass


class DuplicateRoute(NoRoute):
    pass


class RPCError(Exception):
    pass


class RouterRPCError(RPCError):
    pass

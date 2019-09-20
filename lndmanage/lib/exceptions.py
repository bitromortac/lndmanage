class RouteWithTooSmallCapacity(Exception):
    pass


class RebalanceFailure(Exception):
    pass


class NoRouteError(Exception):
    pass


class DryRunException(Exception):
    pass


class PaymentTimeOut(Exception):
    pass


class TooExpensive(Exception):
    pass
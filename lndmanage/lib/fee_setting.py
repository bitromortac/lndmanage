import lndmanage.grpc_compiled.rpc_pb2 as ln

import logging
logger = logging.getLogger('FEESET')
logger.addHandler(logging.NullHandler())

CLTV = 40


def set_fees_by_balancedness(
        node, base_unbalanced_msat, rate_unbalanced_decimal, base_balanced_msat, rate_balanced_decimal,
        unbalancedness=0.90):
    """
    Can be used to set fees differently for balanced and unbalanced channels.
    TODO: refactor out lnd api calls into :class:`lib.node.LndNode`

    :param node: :class:`lib.node.LndNode` instance
    :param base_unbalanced_msat: int
    :param rate_unbalanced_decimal: float (e.g. 0.00001 = 0.001 %)
    :param base_balanced_msat: int
    :param rate_balanced_decimal: float (e.g. 0.00001 = 0.001 %)
    :param unbalancedness: float between 0 ... 1 (0: very balanced, 1: very unbalanced)
    """

    channels = node.get_unbalanced_channels()
    logger.info(f"-------- unbalanced channels (|ub| > {unbalancedness}) ---------")
    channels.sort(key=lambda x: abs(x['unbalancedness']), reverse=True)
    print_divide = 0

    for c in channels:
        logger.info(f"|ub|: {abs(c['unbalancedness']):1.4f} c: {c['chan_id']} a: {c['alias']}")

        cp_parts = c['channel_point'].split(':')

        channel_point = ln.ChannelPoint(funding_txid_str=cp_parts[0], output_index=int(cp_parts[1]))

        if abs(c['unbalancedness']) > unbalancedness:  # unbalanced
            new_base = base_unbalanced_msat
            new_rate = rate_unbalanced_decimal
        else:  # balanced
            if print_divide == 0:
                logger.info(f"-------- balanced channels (|ub| < {unbalancedness}) --------")
                print_divide = 1

            new_base = base_balanced_msat
            new_rate = rate_balanced_decimal

        update_request = ln.PolicyUpdateRequest(
            chan_point=channel_point,
            base_fee_msat=new_base,
            fee_rate=new_rate,
            time_lock_delta=CLTV,
        )
        logger.debug(update_request)

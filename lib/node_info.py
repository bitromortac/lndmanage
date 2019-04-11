import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def print_node_status(node):
    logger.info("-------- Node status --------")
    balancedness_local = node.total_local_balance / node.total_capacity
    balancedness_remote = node.total_remote_balance / node.total_capacity
    logger.info(f"alias: {node.alias}")
    logger.info(f"pub key: {node.pub_key}")
    logger.info(f"blockheight: {node.blockheight}")
    logger.info(f"peers: {node.num_peers}")
    logger.info(f"channels: {node.total_channels}")
    logger.info(f"active channels: {node.total_active_channels}")
    logger.info(f"private channels: {node.total_private_channels}")
    logger.info(f"capacity: {node.total_capacity}")
    logger.info(f"balancedness: l:{balancedness_local:.2%} r:{balancedness_remote:.2%}")
    logger.info(f"total satoshis received (current channels): {node.total_satoshis_received}")
    logger.info(f"total satoshis sent (current channels): {node.total_satoshis_sent}")


def print_unbalanced_channels(node, unbalancedness_greater_than):
    logger.info("-------- Channels --------")
    channels = node.get_unbalanced_channels(unbalancedness_greater_than)
    channels.sort(key=lambda x: x['alias'])
    for c in channels:
        logger.info(
            f"ub:{c['unbalancedness']: 4.2f} cap:{c['capacity']: 9d}"
            f" l:{c['local_balance']: 9d} r:{c['remote_balance']: 9d} b:{c['fees']['base']: 6d}"
            f" r:{c['fees']['rate']/1E6: 1.6f} c:{c['chan_id']} a:{c['alias']}")


if __name__ == '__main__':
    pass

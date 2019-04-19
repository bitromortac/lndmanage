from lib.ln_utilities import convert_channel_id_to_short_channel_id
import time

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def get_channels_hygiene(node):
    """
    Prepares a dict with relevant information for channel hygiene.

    :param node: :class:`lib.node.LndNode`
    :return: dict
    """
    channels = node.get_inactive_channels()
    channel_list = []

    for c in channels:
        # calculate age from blockheight
        blockheight, _, _ = convert_channel_id_to_short_channel_id(c['chan_id'])
        age_days = (node.blockheight - blockheight) * 10 / (60 * 24)
        # calculate last update (days ago)
        try:
            last_update = (time.time() - c['last_update']) / (60 * 60 * 24)
        except TypeError:
            last_update = 0

        sent_received_per_week = int((c['total_satoshis_sent'] + c['total_satoshis_received']) / (age_days / 7))

        # being explicit about what is in dict:
        channel_info = {
            'active': c['active'],
            'age': age_days,
            'alias': c['alias'],
            'capacity': c['capacity'],
            'chan_id': c['chan_id'],
            'commit_fee': c['commit_fee'],
            'initiator': c['initiator'],
            'last_update': last_update,
            'local_balance': c['local_balance'],
            'num_updates': c['num_updates'],
            'private': c['private'],
            'sent_received_per_week': sent_received_per_week,
            'total_satoshis_sent': c['total_satoshis_sent'],
            'total_satoshis_received': c['total_satoshis_received'],
            'unbalancedness': c['unbalancedness'],
        }

        channel_list.append(channel_info)
    # sort by public channel and by last update
    channel_list.sort(key=lambda x: (x['private'], -x['last_update']))

    return channel_list


def print_channels_rebalance(node, unbalancedness_greater_than):
    logger.info("-------- Description --------")
    logger.info(
        "cid: channel id\n"
        "ub: unbalancedness (see --help)\n"
        "c: channel capacity [sats]\n"
        "l: local balance [sats]\n"
        "r: remote balance [sats]\n"
        "bf: peer base fee [msats]\n"
        "fr: peer fee rate\n"
        "a: alias"
    )
    logger.info("-------- Channels --------")
    channels = node.get_unbalanced_channels(unbalancedness_greater_than)
    channels.sort(key=lambda x: x['alias'])
    for c in channels:
        logger.info(
            f"cid:{c['chan_id']} "
            f"ub:{c['unbalancedness']: 4.2f} "
            f"c:{c['capacity']: 9d} "
            f"l:{c['local_balance']: 9d} "
            f"r:{c['remote_balance']: 9d} "
            f"bf:{c['fees']['base']: 6d} "
            f"fr:{c['fees']['rate']/1E6: 1.6f} "
            f"a:{c['alias']}"
        )


def print_channels_hygiene(node):
    logger.info("-------- Description --------")
    logger.info(
        "cid: channel id\n"
        "p: true if private channel\n"
        "o: true if we opened channel\n"
        "upd: last update time [days ago]\n"
        "age: channel age [days]\n"
        "c: capacity [sats]\n"
        "l: local balance [sats]\n"
        "sr/w: satoshis sent + received per week of lifespan\n"
        "a: alias"
    )
    logger.info("-------- Channels --------")
    channels = get_channels_hygiene(node)
    for c in channels:
        logger.info(
            f"cid:{c['chan_id']} "
            f"p:{str(c['private'])[0]} "
            f"o:{str(c['initiator'])[0]} "
            f"upd:{int(c['last_update']): 3d} "
            f"age:{int(c['age']): 4d} "
            f"c:{c['capacity']: 9d} "
            f"l:{c['local_balance']: 9d} "
            f"sr/w:{c['sent_received_per_week']: 8d} "
            f"a:{c['alias']}"
        )


if __name__ == '__main__':
    from lib.node import LndNode

    import _settings
    import logging.config

    logging.config.dictConfig(_settings.logger_config)

    nd = LndNode()
    print_channels_hygiene(nd)

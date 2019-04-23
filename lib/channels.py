from lib.ln_utilities import convert_channel_id_to_short_channel_id
import time

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

channel_abbrev = {
    'active': 'act',
    'age': 'age',
    'alias': 'a',
    'amount_to_balanced': 'atb',
    'capacity': 'cap',
    'chan_id': 'cid',
    'channel_point': 'cpt',
    'commit_fee': 'cf',
    'initiator': 'ini',
    'last_update': 'lup',
    'local_balance': 'lb',
    'num_updates': 'nup',
    'private': 'p',
    'peer_base_fee': 'bf',
    'peer_fee_rate': 'fr',
    'remote_balance': 'rb',
    'remote_pubkey': 'rpk',
    'sent_received_per_week': 'sr/w',
    'total_satoshis_sent': 's/t',
    'total_satoshis_received': 'r/t',
    'unbalancedness': 'ub',
}

channel_abbrev_reverse = {v: k for k, v in channel_abbrev.items()}


def print_channels_rebalance(node, unbalancedness_greater_than, sort_by='a'):
    logger.info("-------- Description --------")
    logger.info(
        f"{channel_abbrev['chan_id']}: channel id\n"
        f"{channel_abbrev['unbalancedness']}: unbalancedness (see --help)\n"
        f"{channel_abbrev['capacity']}: channel capacity [sats]\n"
        f"{channel_abbrev['local_balance']}: local balance [sats]\n"
        f"{channel_abbrev['remote_balance']}: remote balance [sats]\n"
        f"{channel_abbrev['peer_base_fee']}: peer base fee [msats]\n"
        f"{channel_abbrev['peer_fee_rate']}: peer fee rate\n"
        f"{channel_abbrev['alias']}: alias"
    )
    logger.info("-------- Channels --------")
    channels = node.get_unbalanced_channels(unbalancedness_greater_than)
    channels.sort(key=lambda x: x[channel_abbrev_reverse[sort_by]])
    for c in channels:
        logger.info(
            f"{channel_abbrev['chan_id']}: {c['chan_id']} "
            f"{channel_abbrev['unbalancedness']}:{c['unbalancedness']: 4.2f} "
            f"{channel_abbrev['capacity']}:{c['capacity']: 9d} "
            f"{channel_abbrev['local_balance']}:{c['local_balance']: 9d} "
            f"{channel_abbrev['remote_balance']}:{c['remote_balance']: 9d} "
            f"{channel_abbrev['peer_base_fee']}:{c['peer_base_fee']: 6d} "
            f"{channel_abbrev['peer_fee_rate']}:{c['peer_fee_rate']/1E6: 1.6f} "
            f"{channel_abbrev['alias']}: {c['alias']}"
        )


def print_channels_hygiene(node, sort_by='lup'):
    logger.info("-------- Description --------")
    logger.info(
        f"{channel_abbrev['chan_id']}: channel id\n"
        f"{channel_abbrev['private']}: true if private channel\n"
        f"{channel_abbrev['initiator']}: true if we opened channel\n"
        f"{channel_abbrev['last_update']}: last update time [days ago]\n"
        f"{channel_abbrev['age']}: channel age [days]\n"
        f"{channel_abbrev['capacity']}: capacity [sats]\n"
        f"{channel_abbrev['local_balance']}: local balance [sats]\n"
        f"{channel_abbrev['sent_received_per_week']}: satoshis sent + received per week of lifespan\n"
        f"{channel_abbrev['alias']}: alias"
    )
    logger.info("-------- Channels --------")
    channels = node.get_inactive_channels()
    channels.sort(key=lambda x: (x['private'], -x[channel_abbrev_reverse[sort_by]]))

    for c in channels:
        logger.info(
            f"{channel_abbrev['chan_id']}: {c['chan_id']} "
            f"{channel_abbrev['private']}:{str(c['private'])[0]} "
            f"{channel_abbrev['initiator']}:{str(c['initiator'])[0]} "
            f"{channel_abbrev['last_update']}:{c['last_update']: 5.0f} "
            f"{channel_abbrev['age']}:{c['age']: 5.0f} "
            f"{channel_abbrev['capacity']}:{c['capacity']: 9d} "
            f"{channel_abbrev['local_balance']}:{c['local_balance']: 9d} "
            f"{channel_abbrev['sent_received_per_week']}:{c['sent_received_per_week']: 8d} "
            f"{channel_abbrev['alias']}: {c['alias']}"
        )


if __name__ == '__main__':
    from lib.node import LndNode

    import _settings
    import logging.config

    logging.config.dictConfig(_settings.logger_config)

    nd = LndNode()
    print_channels_hygiene(nd)

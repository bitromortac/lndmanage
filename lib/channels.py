import math
from lib.forwardings import get_forwarding_statistics_channels

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
    'fees_total': 'fees',
    'fees_total_per_week': 'f/w',
    'flow_direction': 'flow',
    'initiator': 'ini',
    'last_update': 'lup',
    'local_balance': 'lb',
    'num_updates': 'nup',
    'number_forwardings': 'nfwd',
    'private': 'p',
    'peer_base_fee': 'bf',
    'peer_fee_rate': 'fr',
    'rebalance_required': 'r',
    'remote_balance': 'rb',
    'remote_pubkey': 'rpk',
    'sent_received_per_week': 'sr/w',
    'total_satoshis_sent': 's/t',
    'total_satoshis_received': 'r/t',
    'total_forwarding_in': 'in',
    'total_forwarding_out': 'out',
    'unbalancedness': 'ub',
    'median_forwarding_in': 'imed',
    'largest_forwarding_amount_in': 'imax',
    'median_forwarding_out': 'omed',
    'largest_forwarding_amount_out': 'omax',
}

channel_abbrev_reverse = {v: k for k, v in channel_abbrev.items()}


def print_channels_rebalance(node, unbalancedness_greater_than, sort_by='a'):
    logger.info("-------- Description --------")
    logger.info(
        f"{channel_abbrev['unbalancedness']:<10} unbalancedness (see --help)\n"
        f"{channel_abbrev['capacity']:<10} channel capacity [sats]\n"
        f"{channel_abbrev['local_balance']:<10} local balance [sats]\n"
        f"{channel_abbrev['remote_balance']:<10} remote balance [sats]\n"
        f"{channel_abbrev['peer_base_fee']:<10} peer base fee [msats]\n"
        f"{channel_abbrev['peer_fee_rate']:<10} peer fee rate\n"
        f"{channel_abbrev['chan_id']:<10} channel id\n"
        f"{channel_abbrev['alias']:<10} alias\n"
    )
    logger.info("-------- Channels --------")
    channels = node.get_unbalanced_channels(unbalancedness_greater_than)
    channels.sort(key=lambda x: x[channel_abbrev_reverse[sort_by]])
    for ic, c in enumerate(channels):
        if not(ic % 20):
            logger.info(
                f"{channel_abbrev['chan_id']:^18}"
                f"{channel_abbrev['unbalancedness']:>6}"
                f"{channel_abbrev['capacity']:>10}"
                f"{channel_abbrev['local_balance']:>10}"
                f"{channel_abbrev['remote_balance']:>10}"
                f"{channel_abbrev['peer_base_fee']:>7}"
                f"{channel_abbrev['peer_fee_rate']:>10}"
                f"{channel_abbrev['alias']:^15}"
            )
        logger.info(
            f"{c['chan_id']} "
            f"{c['unbalancedness']: 4.2f} "
            f"{c['capacity']: 9d} "
            f"{c['local_balance']: 9d} "
            f"{c['remote_balance']: 9d} "
            f"{c['peer_base_fee']: 6d} "
            f"{c['peer_fee_rate']/1E6: 1.6f} "
            f"{c['alias']}"
        )


def print_channels_hygiene(node, sort_by='lup'):
    logger.info("-------- Description --------")
    logger.info(
        f"{channel_abbrev['private']:<10} true if private channel\n"
        f"{channel_abbrev['initiator']:<10} true if we opened channel\n"
        f"{channel_abbrev['last_update']:<10} last update time [days ago]\n"
        f"{channel_abbrev['age']:<10} channel age [days]\n"
        f"{channel_abbrev['capacity']:<10} capacity [sats]\n"
        f"{channel_abbrev['local_balance']:<10} local balance [sats]\n"
        f"{channel_abbrev['sent_received_per_week']:<10} satoshis sent + received per week of lifespan\n"
        f"{channel_abbrev['chan_id']:<10} channel id\n"
        f"{channel_abbrev['alias']:<10} alias\n"
    )
    logger.info("-------- Channels --------")
    channels = node.get_inactive_channels()
    channels.sort(key=lambda x: (x['private'], -x[channel_abbrev_reverse[sort_by]]))

    for ic, c in enumerate(channels):
        if not(ic % 20):
            logger.info(
                f"{channel_abbrev['chan_id']:^18}"
                f"{channel_abbrev['private']:>2}"
                f"{channel_abbrev['initiator']:>4}"
                f"{channel_abbrev['last_update']:>6}"
                f"{channel_abbrev['age']:>6}"
                f"{channel_abbrev['capacity']:>10}"
                f"{channel_abbrev['local_balance']:>10}"
                f"{channel_abbrev['sent_received_per_week']:>9}"
                f"{channel_abbrev['alias']:^15}"
            )
        logger.info(
            f"{c['chan_id']}"
            f" {str(c['private'])[0]}"
            f"   {str(c['initiator'])[0]} "
            f"{c['last_update']: 5.0f} "
            f"{c['age']: 5.0f} "
            f"{c['capacity']: 9d} "
            f"{c['local_balance']: 9d} "
            f"{c['sent_received_per_week']: 8d} "
            f"{c['alias']}"
        )


def print_channels_forwardings(node, time_interval_start, time_interval_end, sort_by='f/t'):
    logger.info("-------- Description --------")
    logger.info(
        f"{channel_abbrev['chan_id']:<10} channel id\n"
        f"{channel_abbrev['number_forwardings']:<10} number of forwardings\n"
        f"{channel_abbrev['age']:<10} channel age [days]\n"
        f"{channel_abbrev['fees_total']:<10} fees total [sats]\n"
        f"{channel_abbrev['fees_total_per_week']:<10} fees per week [sats]\n"
        f"{channel_abbrev['unbalancedness']:<10} unbalancedness\n"
        f"{channel_abbrev['flow_direction']:<10} flow direction (positive is outwards)\n"
        f"{channel_abbrev['rebalance_required']:<10} rebalance required if marked with X\n"
        f"{channel_abbrev['capacity']:<10} channel capacity [sats]\n"
        f"{channel_abbrev['total_forwarding_in']:<10} total forwardings inwards [sats]\n"
        f"{channel_abbrev['median_forwarding_in']:<10} median forwarding inwards [sats]\n"
        f"{channel_abbrev['largest_forwarding_amount_in']:<10} largest forwarding inwards [sats]\n"
        f"{channel_abbrev['total_forwarding_out']:<10} total forwardings outwards [sats]\n"
        f"{channel_abbrev['median_forwarding_out']:<10} median forwarding outwards [sats]\n"
        f"{channel_abbrev['largest_forwarding_amount_out']:<10} largest forwarding outwards [sats]\n"
    )
    logger.info("-------- Channels --------")
    channels = get_forwarding_statistics_channels(node, time_interval_start, time_interval_end)
    channels.sort(key=lambda x: (float('inf') if math.isnan(-x[channel_abbrev_reverse[sort_by]]) else -x[channel_abbrev_reverse[sort_by]],
                                 -x[channel_abbrev_reverse['nfwd']],
                                 -x[channel_abbrev_reverse['ub']]))

    for ic, c in enumerate(channels):
        if not(ic % 20):
            logger.info(
                f"{channel_abbrev['chan_id']:^18}"
                f"{channel_abbrev['number_forwardings']:>5}"
                f"{channel_abbrev['age']:>6}"
                f"{channel_abbrev['fees_total']:>6}"
                f"{channel_abbrev['fees_total_per_week']:>8}"
                f"{channel_abbrev['unbalancedness']:>6}"
                f"{channel_abbrev['flow_direction']:>6}"
                f"{channel_abbrev['rebalance_required']:>2}"
                f"{channel_abbrev['capacity']:>9}"
                f"{channel_abbrev['total_forwarding_in']:>11}"
                f"{channel_abbrev['median_forwarding_in']:>8}"
                f"{channel_abbrev['largest_forwarding_amount_in']:>8}"
                f"{channel_abbrev['total_forwarding_out']:>11}"
                f"{channel_abbrev['median_forwarding_out']:>8}"
                f"{channel_abbrev['largest_forwarding_amount_out']:>8}"
            )
        logger.info(
            f"{c['chan_id']} "
            f"{c['number_forwardings']:4.0f} "
            f"{c['age']:5.0f} "
            f"{c['fees_total'] / 1000:5.0f} "
            f"{c['fees_total_per_week'] / 1000:7.3f} "
            f"{c['unbalancedness']:5.2f} "
            f"{c['flow_direction']:5.2f} "
            f"{'X' if c['rebalance_required'] else ' '} "
            f"{c['capacity']:8.0f} "
            f"| {c['total_forwarding_in']:8.0f} "
            f"{c['median_forwarding_in']:7.0f} "
            f"{c['largest_forwarding_amount_in']:7.0f} "
            f"| {c['total_forwarding_out']:8.0f} "
            f"{c['median_forwarding_out']:7.0f} "
            f"{c['largest_forwarding_amount_out']:7.0f} "
        )


if __name__ == '__main__':
    from lib.node import LndNode

    import _settings
    import logging.config

    logging.config.dictConfig(_settings.logger_config)

    nd = LndNode()
    print_channels_hygiene(nd)

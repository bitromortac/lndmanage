import math
from collections import OrderedDict

from lib.forwardings import get_forwarding_statistics_channels

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

abbreviations = {
    'active': 'act',
    'age': 'age',
    'alias': 'a',
    'amount_to_balanced': 'atb',
    'bandwidth_demand': 'bwd',
    'capacity': 'cap',
    'capacity_per_channel': 'cpc',
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
    'number_channels': 'nchan',
    'private': 'p',
    'peer_base_fee': 'bf',
    'peer_fee_rate': 'fr',
    'rebalance_required': 'r',
    'remote_balance': 'rb',
    'remote_pubkey': 'rpk',
    'sent_received_per_week': 'sr/w',
    'total_capacity': 'tcap',
    'total_satoshis_sent': 's/t',
    'total_satoshis_received': 'r/t',
    'total_forwarding_in': 'in',
    'total_forwarding_out': 'out',
    'total_forwarding': 'tot',
    'unbalancedness': 'ub',
    'median_forwarding_in': 'imed',
    'mean_forwarding_in': 'imean',
    'largest_forwarding_amount_in': 'imax',
    'median_forwarding_out': 'omed',
    'mean_forwarding_out': 'omean',
    'largest_forwarding_amount_out': 'omax',
}

abbreviations_reverse = {v: k for k, v in abbreviations.items()}


def print_channels_rebalance(node, unbalancedness_greater_than, sort_by='a'):
    logger.info("-------- Description --------")
    logger.info(
        f"{abbreviations['unbalancedness']:<10} unbalancedness (see --help)\n"
        f"{abbreviations['capacity']:<10} channel capacity [sats]\n"
        f"{abbreviations['local_balance']:<10} local balance [sats]\n"
        f"{abbreviations['remote_balance']:<10} remote balance [sats]\n"
        f"{abbreviations['peer_base_fee']:<10} peer base fee [msats]\n"
        f"{abbreviations['peer_fee_rate']:<10} peer fee rate\n"
        f"{abbreviations['chan_id']:<10} channel id\n"
        f"{abbreviations['alias']:<10} alias\n"
    )
    logger.info("-------- Channels --------")
    channels = node.get_unbalanced_channels(unbalancedness_greater_than)
    channels = OrderedDict(sorted(channels.items(), key=lambda x: x[1][abbreviations_reverse[sort_by]]))

    for ic, (k, c) in enumerate(channels.items()):
        if not(ic % 20):
            logger.info(
                f"{abbreviations['chan_id']:^18}"
                f"{abbreviations['unbalancedness']:>6}"
                f"{abbreviations['capacity']:>10}"
                f"{abbreviations['local_balance']:>10}"
                f"{abbreviations['remote_balance']:>10}"
                f"{abbreviations['peer_base_fee']:>7}"
                f"{abbreviations['peer_fee_rate']:>10}"
                f"{abbreviations['alias']:^15}"
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
        f"{abbreviations['private']:<10} true if private channel\n"
        f"{abbreviations['initiator']:<10} true if we opened channel\n"
        f"{abbreviations['last_update']:<10} last update time [days ago]\n"
        f"{abbreviations['age']:<10} channel age [days]\n"
        f"{abbreviations['capacity']:<10} capacity [sats]\n"
        f"{abbreviations['local_balance']:<10} local balance [sats]\n"
        f"{abbreviations['sent_received_per_week']:<10} satoshis sent + received per week of lifespan\n"
        f"{abbreviations['chan_id']:<10} channel id\n"
        f"{abbreviations['alias']:<10} alias\n"
    )
    logger.info("-------- Channels --------")
    channels = node.get_inactive_channels()
    channels = OrderedDict(sorted(channels.items(), key=lambda x: (x[1]['private'],
                                                                   -x[1][abbreviations_reverse[sort_by]])))

    for ic, (k, c) in enumerate(channels.items()):
        if not(ic % 20):
            logger.info(
                f"{abbreviations['chan_id']:^18}"
                f"{abbreviations['private']:>2}"
                f"{abbreviations['initiator']:>4}"
                f"{abbreviations['last_update']:>6}"
                f"{abbreviations['age']:>6}"
                f"{abbreviations['capacity']:>10}"
                f"{abbreviations['local_balance']:>10}"
                f"{abbreviations['sent_received_per_week']:>9}"
                f"{abbreviations['alias']:^15}"
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
        f"{abbreviations['chan_id']:<10} channel id\n"
        f"{abbreviations['number_forwardings']:<10} number of forwardings\n"
        f"{abbreviations['age']:<10} channel age [days]\n"
        f"{abbreviations['fees_total']:<10} fees total [sats]\n"
        f"{abbreviations['fees_total_per_week']:<10} fees per week [sats]\n"
        f"{abbreviations['unbalancedness']:<10} unbalancedness\n"
        f"{abbreviations['flow_direction']:<10} flow direction (positive is outwards)\n"
        f"{abbreviations['bandwidth_demand']:<10} bandwidth demand: capacity / max(mean_in, mean_out)\n"
        f"{abbreviations['rebalance_required']:<10} rebalance required if marked with X\n"
        f"{abbreviations['capacity']:<10} channel capacity [sats]\n"
        f"{abbreviations['total_forwarding_in']:<10} total forwardings inwards [sats]\n"
        f"{abbreviations['mean_forwarding_in']:<10} mean forwarding inwards [sats]\n"
        f"{abbreviations['largest_forwarding_amount_in']:<10} largest forwarding inwards [sats]\n"
        f"{abbreviations['total_forwarding_out']:<10} total forwardings outwards [sats]\n"
        f"{abbreviations['mean_forwarding_out']:<10} mean forwarding outwards [sats]\n"
        f"{abbreviations['largest_forwarding_amount_out']:<10} largest forwarding outwards [sats]\n"
        f"{abbreviations['alias']:<10} alias\n"
    )
    logger.info("-------- Channels --------")
    channels = get_forwarding_statistics_channels(node, time_interval_start, time_interval_end)
    channels = OrderedDict(sorted(channels.items(),
                                  key=lambda x: (float('inf') if math.isnan(-x[1][abbreviations_reverse[sort_by]])
                                                 else -x[1][abbreviations_reverse[sort_by]],
                                                 -x[1][abbreviations_reverse['nfwd']],
                                                 -x[1][abbreviations_reverse['ub']])))

    for ic, (k, c) in enumerate(channels.items()):
        if not(ic % 20):
            logger.info(
                f"{abbreviations['chan_id']:^18}"
                f"{abbreviations['number_forwardings']:>5}"
                f"{abbreviations['age']:>6}"
                f"{abbreviations['fees_total']:>6}"
                f"{abbreviations['fees_total_per_week']:>8}"
                f"{abbreviations['unbalancedness']:>6}"
                f"{abbreviations['flow_direction']:>6}"
                f"{abbreviations['bandwidth_demand']:>5}"
                f"{abbreviations['rebalance_required']:>2}"
                f"{abbreviations['capacity']:>9}"
                f"{abbreviations['total_forwarding_in']:>9}"
                f"{abbreviations['mean_forwarding_in']:>8}"
                f"{abbreviations['largest_forwarding_amount_in']:>8}"
                f"{abbreviations['total_forwarding_out']:>9}"
                f"{abbreviations['mean_forwarding_out']:>8}"
                f"{abbreviations['largest_forwarding_amount_out']:>8}"
                f"{abbreviations['alias']:^15}"
            )
        logger.info(
            f"{c['chan_id']} "
            f"{c['number_forwardings']:4.0f} "
            f"{c['age']:5.0f} "
            f"{c['fees_total'] / 1000:5.0f} "
            f"{c['fees_total_per_week'] / 1000:7.3f} "
            f"{c['unbalancedness']:5.2f} "
            f"{c['flow_direction']:5.2f} "
            f"{c['bandwidth_demand']:3.2f} "
            f"{'X' if c['rebalance_required'] else ' '} "
            f"{c['capacity']:8.0f} "
            f"{c['total_forwarding_in']:8.0f} "
            f"{c['mean_forwarding_in']:7.0f} "
            f"{c['largest_forwarding_amount_in']:7.0f} "
            f"{c['total_forwarding_out']:8.0f} "
            f"{c['mean_forwarding_out']:7.0f} "
            f"{c['largest_forwarding_amount_out']:7.0f} "
            f"{c['alias'][:10] + '...' if len(c['alias']) > 10 else c['alias']} "
        )

if __name__ == '__main__':
    from lib.node import LndNode

    import _settings
    import logging.config

    logging.config.dictConfig(_settings.logger_config)

    nd = LndNode()
    print_channels_hygiene(nd)

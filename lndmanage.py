#!/usr/bin/env python
import argparse
import time
import os

from lib.node import LndNode
from lib.listchannels import ListChannels
from lib.rebalance import Rebalancer
from lib.exceptions import (
    DryRunException,
    PaymentTimeOut,
    TooExpensive,
    RebalanceFailure)
from lib.recommend_nodes import RecommendNodes

import _settings


def range_limited_float_type(unchecked_value):
    """
    Type function for argparse - a float within some predefined bounds

    :param: unchecked_value: float
    """
    try:
        value = float(unchecked_value)
    except ValueError:
        raise argparse.ArgumentTypeError("Must be a floating point number")
    if value < 1E-6 or value > 1:
        raise argparse.ArgumentTypeError(
            "Argument must be < " + str(1E-6) + " and > " + str(1))
    return value


def unbalanced_float(x):
    """
    Checks if the value is a valid unbalancedness between [-1 ... 1]
    """
    x = float(x)
    if x < -1.0 or x > 1.0:
        raise argparse.ArgumentTypeError(f"{x} not in range [-1.0, 1.0]")
    return x


class Parser(object):
    def __init__(self):
        # setup the command line parser
        self.parser = argparse.ArgumentParser(
            prog='lndmanage.py',
            description='Lightning network daemon channel management tool.')
        self.parser.add_argument(
            '--loglevel', default='INFO', choices=['INFO', 'DEBUG'])
        subparsers = self.parser.add_subparsers(dest='cmd')

        # cmd: status
        self.parser_status = subparsers.add_parser(
            'status', help='display node status',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        # cmd: listchannels
        self.parser_listchannels = subparsers.add_parser(
            'listchannels',
            help='lists channels with extended information '
                 '[see also subcommands with -h]',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        listchannels_subparsers = self.parser_listchannels.add_subparsers(
            dest='subcmd')

        # subcmd: listchannels rebalance
        parser_listchannels_rebalance = listchannels_subparsers.add_parser(
            'rebalance', help='displays unbalanced channels')
        parser_listchannels_rebalance.add_argument(
            '--unbalancedness', type=float,
            default=_settings.UNBALANCED_CHANNEL,
            help='Unbalancedness is a way to express how balanced a '
                 'channel is, a value between [-1, 1] (a perfectly balanced '
                 'channel has a value of 0). The flag excludes channels with '
                 'an absolute unbalancedness smaller than UNBALANCEDNESS.')
        parser_listchannels_rebalance.add_argument(
            '--sort-by', default='rev_ub', type=str,
            help='sort by column (look at description)')

        # subcmd: listchannels inactive
        parser_listchannels_inactive = listchannels_subparsers.add_parser(
            'inactive', help="displays inactive channels")
        parser_listchannels_inactive.add_argument(
            '--sort-by', default='lup', type=str,
            help='sort by column (look at description)')

        # subcmd: listchannels forwardings
        parser_listchannels_forwardings = listchannels_subparsers.add_parser(
            'forwardings',
            help="displays channels with forwarding information")
        parser_listchannels_forwardings.add_argument(
            '--from-days-ago', default=365, type=int,
            help='time interval start (days ago)')
        parser_listchannels_forwardings.add_argument(
            '--to-days-ago', default=0, type=int,
            help='time interval end (days ago)')
        parser_listchannels_forwardings.add_argument(
            '--sort-by', default='f/w', type=str,
            help='sort by column (look at description)')

        # cmd: rebalance
        self.parser_rebalance = subparsers.add_parser(
            'rebalance', help='rebalance a channel',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser_rebalance.add_argument('channel', type=int,
                                           help='channel_id')
        self.parser_rebalance.add_argument(
            '--max-fee-sat', type=int, default=20,
            help='Sets the maximal fees in satoshis to be paid.')
        self.parser_rebalance.add_argument(
            '--chunksize', type=float, default=1.0,
            help='Specifies if the individual rebalance attempts should be '
                 'split into smaller relative amounts. This increases success'
                 ' rates, but also increases costs!')
        self.parser_rebalance.add_argument(
            '--max-fee-rate', type=range_limited_float_type, default=5E-5,
            help='Sets the maximal effective fee rate to be paid.'
                 ' The effective fee rate is defined by '
                 '(base_fee + amt * fee_rate) / amt.')
        self.parser_rebalance.add_argument(
            '--reckless', help='Execute action in the network.',
            action='store_true')
        self.parser_rebalance.add_argument(
            '--allow-unbalancing',
            help=f'Allow channels to get an unbalancedness'
            f' up to +-{_settings.UNBALANCED_CHANNEL}.',
            action='store_true')
        self.parser_rebalance.add_argument(
            '--target', help=f'This feature is still experimental! '
            f'The unbalancedness target is between [-1, 1]. '
            f'A target of -1 leads to a maximal local balance, a target of 0 '
            f'to a 50:50 balanced channel and a target of 1 to a maximal '
            f'remote balance. Default is a target of 0.',
            type=unbalanced_float, default=None)
        rebalancing_strategies = ['most-affordable-first',
                                  'lowest-feerate-first', 'match-unbalanced']
        self.parser_rebalance.add_argument(
            '--strategy',
            help=f'Rebalancing strategy.',
            choices=rebalancing_strategies, type=str, default=None)

        # cmd: circle
        self.parser_circle = subparsers.add_parser(
            'circle', help='circular self-payment',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser_circle.add_argument('channel_from', type=int,
                                        help='channel_from')
        self.parser_circle.add_argument('channel_to', type=int,
                                        help='channel_from')
        self.parser_circle.add_argument('amt_sat', type=int,
                                        help='amount in satoshis')
        self.parser_circle.add_argument(
            '--max-fee-sat', type=int, default=20,
            help='Sets the maximal fees in satoshis to be paid.')
        self.parser_circle.add_argument(
            '--max-fee-rate', type=range_limited_float_type, default=5E-5,
            help='Sets the maximal effective fee rate to be paid. '
                 'The effective fee rate is defined by '
                 '(base_fee + amt * fee_rate) / amt.')
        self.parser_circle.add_argument(
            '--reckless', help='Execute action in the network.',
            action='store_true')

        # cmd: recommend-nodes
        self.parser_recommend_nodes = subparsers.add_parser(
            'recommend-nodes',
            help='recommends nodes [see also subcommands with -h]',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser_recommend_nodes.add_argument(
            '--show-connected', action='store_true', default=False,
            help='specifies if already connected nodes should be '
                 'removed from list')
        self.parser_recommend_nodes.add_argument(
            '--show-addresses', action='store_true', default=False,
            help='specifies if node addresses should be shown')
        parser_recommend_nodes_subparsers = \
            self.parser_recommend_nodes.add_subparsers(
                dest='subcmd')

        # TODO: put global options to the
        #  parent parser (e.g. number of nodes, sort-by flag)

        # subcmd: recommend-nodes good-old
        parser_recommend_nodes_good_old = \
            parser_recommend_nodes_subparsers.add_parser(
                'good-old',
                help='shows nodes already interacted with but no '
                     'active channels',
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_good_old.add_argument(
            '--nnodes', default=20, type=int,
            help='sets the number of nodes displayed')
        parser_recommend_nodes_good_old.add_argument(
            '--sort-by', default='tot', type=str,
            help="sort by column [abbreviation, e.g. 'tot']")

        # subcmd: recommend-nodes flow-analysis
        parser_recommend_nodes_flow_analysis = \
            parser_recommend_nodes_subparsers.add_parser(
                'flow-analysis', help='recommends nodes from a flow analysis',
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_flow_analysis.add_argument(
            '--nnodes', default=20, type=int,
            help='sets the number of nodes displayed')
        parser_recommend_nodes_flow_analysis.add_argument(
            '--forwarding-events', default=200, type=int,
            help='sets the number of forwarding events in the flow analysis')
        parser_recommend_nodes_flow_analysis.add_argument(
            '--inwards', action='store_true',
            help='if True, inward-flowing nodes are displayed '
                 'instead of outward-flowing nodes')
        parser_recommend_nodes_flow_analysis.add_argument(
            '--sort-by', default='weight', type=str,
            help="sort by column [abbreviation, e.g. 'nchan']")

        # subcmd: recommend-nodes external_source
        parser_recommend_nodes_external_source = \
            parser_recommend_nodes_subparsers.add_parser(
                'external-source', help='recommends nodes from a given file/url',
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_external_source.add_argument(
            '--nnodes', default=20, type=int,
            help='sets the number of nodes displayed')
        parser_recommend_nodes_external_source.add_argument(
            '--source', type=str,
            default='https://github.com/lightningnetworkstores/'
                    'lightningnetworkstores.github.io/raw/master/sites.json',
            help='url/file to be analyzed')
        parser_recommend_nodes_external_source.add_argument(
            '--distributing-nodes', action='store_true',
            help='if True, distributing nodes are '
                 'displayed instead of the bare nodes')
        parser_recommend_nodes_external_source.add_argument(
            '--sort-by', default='cpc', type=str,
            help="sort by column [abbreviation, e.g. 'nchan']")

        # subcmd: recommend-nodes channel-openings
        parser_recommend_nodes_channel_openings = \
            parser_recommend_nodes_subparsers.add_parser(
                'channel-openings',
                help='recommends nodes from recent channel openings',
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_channel_openings.add_argument(
            '--nnodes', default=20, type=int,
            help='sets the number of nodes displayed')
        parser_recommend_nodes_channel_openings.add_argument(
            '--from-days-ago', type=int,
            default=30,
            help='channel openings starting from a time frame days ago')
        parser_recommend_nodes_channel_openings.add_argument(
            '--sort-by', default='msteady', type=str,
            help="sort by column [abbreviation, e.g. 'nchan']")

    def parse_arguments(self):
        return self.parser.parse_args()


def main():
    parser = Parser()
    args = parser.parse_arguments()
    # print(args)

    if args.cmd is None:
        parser.parser.print_help()
        return 0

    # program execution
    if args.loglevel:
        # update the loglevel of the stdout handler to the user choice
        logger.handlers[0].setLevel(args.loglevel)

    # config.ini is expected to be in root directory
    root_dir = os.path.dirname(os.path.realpath(__file__))
    config_file = os.path.join(root_dir, 'config.ini')
    node = LndNode(config_file=config_file)

    if args.cmd == 'status':
        node.print_status()

    elif args.cmd == 'listchannels':
        listchannels = ListChannels(node)
        if not args.subcmd:
            listchannels.print_all_channels('rev_alias')
        if args.subcmd == 'rebalance':
            listchannels.print_channels_unbalanced(
                args.unbalancedness, sort_string=args.sort_by)
        elif args.subcmd == 'inactive':
            listchannels.print_channels_inactive(
                sort_string=args.sort_by)
        elif args.subcmd == 'forwardings':
            # convert time interval into unix timestamp
            time_from = time.time() - args.from_days_ago * 24 * 60 * 60
            time_to = time.time() - args.to_days_ago * 24 * 60 * 60
            listchannels.print_channels_forwardings(
                time_interval_start=time_from, time_interval_end=time_to,
                sort_string=args.sort_by)

    elif args.cmd == 'rebalance':
        if args.target:
            logger.warning("Warning: Target is set, this is still an "
                           "experimental feature.")
        rebalancer = Rebalancer(node, args.max_fee_rate, args.max_fee_sat)
        try:
            rebalancer.rebalance(
                args.channel, dry=not args.reckless, chunksize=args.chunksize,
                target=args.target, allow_unbalancing=args.allow_unbalancing,
                strategy=args.strategy)
        except RebalanceFailure as e:
            logger.error(f"Error: {e}")

    elif args.cmd == 'circle':
        rebalancer = Rebalancer(node, args.max_fee_rate, args.max_fee_sat)
        invoice_r_hash = node.get_rebalance_invoice(memo='circular payment')
        try:
            rebalancer.rebalance_two_channels(
                args.channel_from, args.channel_to,
                args.amt_sat, invoice_r_hash, args.max_fee_sat,
                dry=not args.reckless)
        except DryRunException:
            logger.info("This was just a dry run.")
        except TooExpensive:
            logger.error("Payment failed. This is likely due to a too low "
                         "default --max-fee-rate.")
        except PaymentTimeOut:
            logger.error("Payment failed because the payment timed out. "
                         "This is an unresolved issue.")

    elif args.cmd == 'recommend-nodes':
        if not args.subcmd:
            parser.parser_recommend_nodes.print_help()
            return 0

        recommend_nodes = RecommendNodes(
            node, show_connected=args.show_connected,
            show_addresses=args.show_addresses)

        if args.subcmd == 'good-old':
            recommend_nodes.print_good_old(number_of_nodes=args.nnodes,
                                           sort_by=args.sort_by)
        elif args.subcmd == 'flow-analysis':
            recommend_nodes.print_flow_analysis(
                out_direction=(not args.inwards),
                number_of_nodes=args.nnodes,
                forwarding_events=args.forwarding_events,
                sort_by=args.sort_by)
        elif args.subcmd == 'external-source':
            recommend_nodes.print_external_source(
                args.source, distributing_nodes=args.distributing_nodes,
                number_of_nodes=args.nnodes, sort_by=args.sort_by)
        elif args.subcmd == 'channel-openings':
            recommend_nodes.print_channel_openings(
                from_days_ago=args.from_days_ago,
                number_of_nodes=args.nnodes, sort_by=args.sort_by)


if __name__ == '__main__':
    import logging.config

    logging.config.dictConfig(_settings.logger_config)
    logger = logging.getLogger()

    main()

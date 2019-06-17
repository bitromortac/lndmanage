#!/usr/bin/env python
import argparse
import _settings
import time

from lib.node import LndNode
from lib.listchannels import print_channels_rebalance, print_channels_hygiene, print_channels_forwardings
from lib.rebalance import Rebalancer
from lib.exceptions import DryRunException, PaymentTimeOut, TooExpensive, RebalanceFailure
from lib.recommend_nodes import RecommendNodes


def range_limited_float_type(arg):
    """ Type function for argparse - a float within some predefined bounds """
    try:
        f = float(arg)
    except ValueError:
        raise argparse.ArgumentTypeError("Must be a floating point number")
    if f < 1E-6 or f > 1:
        raise argparse.ArgumentTypeError("Argument must be < " + str(1E-6) + " and > " + str(1))
    return f


def unbalanced_float(x):
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
        self.parser.add_argument('--loglevel', default='INFO', choices=['INFO', 'DEBUG'])
        subparsers = self.parser.add_subparsers(dest='cmd')

        # cmd: status
        self.parser_status = subparsers.add_parser(
            'status', help='display node status',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        # cmd: listchannels
        self.parser_listchannels = subparsers.add_parser(
            'listchannels', help='lists channels with extended information [see also subcommands with -h]',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        listchannels_subparsers = self.parser_listchannels.add_subparsers(dest='subcmd')

        # subcmd: listchannels rebalance
        parser_listchannels_rebalance = listchannels_subparsers.add_parser(
            'rebalance', help='displays unbalanced channels')
        parser_listchannels_rebalance.add_argument(
            '--unbalancedness', type=float,
            default=0.5,
            help='Unbalancedness is a way to express how balanced a channel is, '
                 'a value between [-1, 1] (a perfectly balanced channel has a value of 0). '
                 'The flag excludes channels with an absolute unbalancedness smaller than UNBALANCEDNESS.')

        # subcmd: listchannels inactive
        parser_listchannels_inactive = listchannels_subparsers.add_parser(
            'inactive', help="displays inactive channels")

        # subcmd: listchannels forwardings
        parser_listchannels_forwardings = listchannels_subparsers.add_parser(
            'forwardings', help="displays channels with forwarding information")
        parser_listchannels_forwardings.add_argument(
            '--sort-by', default='f/w', type=str, help='sort by column (look at description)')
        parser_listchannels_forwardings.add_argument(
            '--from-days-ago', default=365, type=int, help='time interval start (days ago)')
        parser_listchannels_forwardings.add_argument(
            '--to-days-ago', default=0, type=int, help='time interval end (days ago)')

        # cmd: rebalance
        self.parser_rebalance = subparsers.add_parser(
            'rebalance', help='rebalance a channel', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser_rebalance.add_argument('channel', type=int, help='channel_id')
        self.parser_rebalance.add_argument(
            '--max-fee-sat', type=int, default=20, help='Sets the maximal fees in satoshis to be paid.')
        self.parser_rebalance.add_argument(
            '--chunksize', type=float, default=1.0, help='Specifies if the individual rebalance attempts should be '
                                                         'split into smaller relative amounts. This increases success'
                                                         ' rates, but also increases costs!')
        self.parser_rebalance.add_argument(
            '--max-fee-rate', type=range_limited_float_type, default=5E-5,
            help='Sets the maximal effective fee rate to be paid.'
                 ' The effective fee rate is defined by (base_fee + amt * fee_rate) / amt.')
        self.parser_rebalance.add_argument(
            '--reckless', help='Execute action in the network.', action='store_true')
        self.parser_rebalance.add_argument(
            '--allow-unbalancing', help=f'Allow channels to get an unbalancedness'
            f' up to +-{_settings.UNBALANCED_CHANNEL}.',
            action='store_true')
        self.parser_rebalance.add_argument(
            '--target', help=f'This feature is still experimental!'
            f' The unbalancedness target is between [-1, 1].'
            f' A target of -1 leads to a maximal local balance, a target of 0'
            f' to a 50:50 balanced channel and a target of 1 to a maximal remote balance. Default is a target of 0.',
            type=unbalanced_float, default=None)
        rebalancing_strategies = ['most-affordable-first', 'lowest-feerate-first', 'match-unbalanced']
        self.parser_rebalance.add_argument(
            '--strategy',
            help=f'Rebalancing strategy.',
            choices=rebalancing_strategies, type=str, default=None)

        # cmd: circle
        self.parser_circle = subparsers.add_parser(
            'circle', help='circular self-payment', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser_circle.add_argument('channel_from', type=int, help='channel_from')
        self.parser_circle.add_argument('channel_to', type=int, help='channel_from')
        self.parser_circle.add_argument('amt_sats', type=int, help='amount in satoshis')
        self.parser_circle.add_argument(
            '--max-fee-sat', type=int, default=20, help='Sets the maximal fees in satoshis to be paid.')
        self.parser_circle.add_argument(
            '--max-fee-rate', type=range_limited_float_type, default=5E-5,
            help='Sets the maximal effective fee rate to be paid.'
                 ' The effective fee rate is defined by (base_fee + amt * fee_rate) / amt.')
        self.parser_circle.add_argument(
            '--reckless', help='Execute action in the network.', action='store_true')

        # cmd: recommend-node
        self.parser_recommend_nodes = subparsers.add_parser(
            'recommend-nodes', help='recommends nodes [see also subcommands with -h]',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser_recommend_nodes.add_argument(
            '--show-connected', action='store_true', default=False,
            help='specifies if already connected nodes should be removed from list')
        self.parser_recommend_nodes.add_argument(
            '--show-addresses', action='store_true', default=False,
            help='specifies if node addresses should be shown')
        parser_recommend_nodes_subparsers = self.parser_recommend_nodes.add_subparsers(dest='subcmd')

        # subcmd: recommend-node good-old
        parser_recommend_nodes_good_old = parser_recommend_nodes_subparsers.add_parser(
            'good-old', help='shows nodes already interacted with but no active channels',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_good_old.add_argument(
            '--nnodes', default=20, type=int, help='sets the number of nodes displayed')
        parser_recommend_nodes_good_old.add_argument(
            '--sort-by', default='tot', type=str, help="sort by column [abbreviation, e.g. 'tot']")

        # subcmd: recommend-node flow-analysis
        parser_recommend_nodes_flow_analysis = parser_recommend_nodes_subparsers.add_parser(
            'flow-analysis', help='recommends nodes from a flow analysis',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_flow_analysis.add_argument(
            '--nnodes', default=20, type=int, help='sets the number of nodes displayed')
        parser_recommend_nodes_flow_analysis.add_argument(
            '--forwarding-events', default=200, type=int,
            help='sets the number of forwarding events in the flow analysis')
        parser_recommend_nodes_flow_analysis.add_argument(
            '--inwarding-nodes', action='store_true',
            help='if True, inwarding nodes are displayed instead of outwarding')

        # subcmd: recommend-node nodefile
        parser_recommend_nodes_nodefile = parser_recommend_nodes_subparsers.add_parser(
            'nodefile', help='recommends nodes from a given file/url',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_nodefile.add_argument(
            '--nnodes', default=20, type=int, help='sets the number of nodes displayed')
        parser_recommend_nodes_nodefile.add_argument(
            '--source', type=str,
            default='https://github.com/lightningnetworkstores/lightningnetworkstores.github.io/raw/master/sites.json',
            help='url/file to be analyzed')
        parser_recommend_nodes_nodefile.add_argument(
            '--distributing-nodes', action='store_true',
            help='if True, distributing nodes are displayed instead of the bare nodes')
        parser_recommend_nodes_nodefile.add_argument(
            '--sort-by', default='cpc', type=str, help="sort by column [abbreviation, e.g. 'nchan']")

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

    node = LndNode()

    if args.cmd == 'status':
        node.print_status()

    elif args.cmd == 'listchannels':
        if not args.subcmd:
            print_channels_rebalance(node, unbalancedness_greater_than=0)
        if args.subcmd == 'rebalance':
            print_channels_rebalance(node, args.unbalancedness, sort_by='ub')
        elif args.subcmd == 'inactive':
            print_channels_hygiene(node)
        elif args.subcmd == 'forwardings':
            # convert time interval into unix timestamp
            time_from = time.time() - args.from_days_ago * 24 * 60 * 60
            time_to = time.time() - args.to_days_ago * 24 * 60 * 60
            print_channels_forwardings(
                node, sort_by=args.sort_by, time_interval_start=time_from, time_interval_end=time_to)

    elif args.cmd == 'rebalance':
        if args.target:
            logger.warning("Warning: Target is set, this is still an experimental feature.")
        rebalancer = Rebalancer(node, args.max_fee_rate, args.max_fee_sat)
        try:
            rebalancer.rebalance(
                args.channel, dry=not args.reckless, chunksize=args.chunksize, target=args.target,
                allow_unbalancing=args.allow_unbalancing, strategy=args.strategy)
        except RebalanceFailure as e:
            logger.error(f"Error: {e}")

    elif args.cmd == 'circle':
        rebalancer = Rebalancer(node, args.max_fee_rate, args.max_fee_sat)
        invoice_r_hash = node.get_rebalance_invoice(memo='circular payment')
        try:
            rebalancer.rebalance_two_channels(
                args.channel_from, args.channel_to,
                args.amt_sats, invoice_r_hash, args.max_fee_sat, dry=not args.reckless)
        except DryRunException:
            logger.info("This was just a dry run.")
        except TooExpensive:
            logger.error("Payment failed. This is likely due to a too low default --max-fee-rate.")
        except PaymentTimeOut:
            logger.error("Payment failed because the payment timed out. This is an unresolved issue.")

    elif args.cmd == 'recommend-nodes':
        if not args.subcmd:
            parser.parser_recommend_nodes.print_help()
            return 0

        recommend_nodes = RecommendNodes(node, show_connected=args.show_connected, show_addresses=args.show_addresses)

        if args.subcmd == 'good-old':
            recommend_nodes.print_good_old(number_of_nodes=args.nnodes, sort_by=args.sort_by)
        elif args.subcmd == 'flow-analysis':
            recommend_nodes.print_flow_analysis(out_direction=(not args.inwarding_nodes),
                                                number_of_nodes=args.nnodes, forwarding_events=args.forwarding_events)
        elif args.subcmd == 'nodefile':
            recommend_nodes.print_nodefile(args.source, distributing_nodes=args.distributing_nodes,
                                           number_of_nodes=args.nnodes, sort_by=args.sort_by)


if __name__ == '__main__':
    import logging.config
    logging.config.dictConfig(_settings.logger_config)
    logger = logging.getLogger()

    main()

#!/usr/bin/env python
import argparse
import time
import os
import sys
import distutils.spawn as spawn
# readline has a desired side effect on keyword input of enabling history
import readline

from lndmanage.lib.node import LndNode
from lndmanage.lib.listchannels import ListChannels
from lndmanage.lib.rebalance import Rebalancer
from lndmanage.lib.recommend_nodes import RecommendNodes
from lndmanage.lib.report import Report
from lndmanage.lib.info import Info
from lndmanage.lib.lncli import Lncli
from lndmanage.lib.exceptions import (
    DryRun,
    PaymentTimeOut,
    TooExpensive,
    RebalanceFailure,
    RebalancingTrialsExhausted,
)
from lndmanage import settings

import logging.config
logging.config.dictConfig(settings.logger_config)
logger = logging.getLogger()


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

        # figure out if lncli is available and determine path of executable
        self.lncli = False
        self.lncli_path = None

        self.check_for_lncli()

        # setup the command line parser
        self.parser = argparse.ArgumentParser(
            prog='lndmanage.py',
            description='Lightning network daemon channel management tool.')
        self.parser.add_argument(
            '--loglevel', default='INFO', choices=['INFO', 'DEBUG'])
        subparsers = self.parser.add_subparsers(dest='cmd')

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
            default=settings.UNBALANCED_CHANNEL,
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
            '--sort-by', default='lupp', type=str,
            help='sort by column (look at description)')

        # subcmd: listchannels forwardings
        parser_listchannels_forwardings = listchannels_subparsers.add_parser(
            'forwardings',
            help="displays channels with forwarding information")
        parser_listchannels_forwardings.add_argument(
            '--from-days-ago', default=30, type=int,
            help='time interval start (days ago)')
        parser_listchannels_forwardings.add_argument(
            '--to-days-ago', default=0, type=int,
            help='time interval end (days ago)')
        parser_listchannels_forwardings.add_argument(
            '--sort-by', default='f/w', type=str,
            help='sort by column (look at description)')

        # subcmd: listchannels hygiene
        parser_listchannels_hygiene = listchannels_subparsers.add_parser(
            'hygiene',
            help="displays channels with information for channel closing")
        parser_listchannels_hygiene.add_argument(
            '--from-days-ago', default=60, type=int,
            help='time interval start (days ago)')
        parser_listchannels_hygiene.add_argument(
            '--sort-by', default='rev_nfwd', type=str,
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
            f' up to +-{settings.UNBALANCED_CHANNEL}.',
            action='store_true')
        self.parser_rebalance.add_argument(
            '--target', help=f'This feature is still experimental! '
            f'The unbalancedness target is between [-1, 1]. '
            f'A target of -1 leads to a maximal local balance, a target of 0 '
            f'to a 50:50 balanced channel and a target of 1 to a maximal '
            f'remote balance. Default is a target of 0.',
            type=unbalanced_float, default=0.0)
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
                help='nodes with previous good relationship (channels)',
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
                'flow-analysis', help='nodes from a flow analysis',
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
                'external-source',
                help='nodes from a given file/url',
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
                help='nodes from recent channel openings',
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

        # subcmd: recommend-nodes second-neighbors
        parser_recommend_nodes_second_neighbors = \
            parser_recommend_nodes_subparsers.add_parser(
                'second-neighbors',
                help='nodes from network analysis giving most '
                     'second neighbors',
                description="This command recommends nodes for getting more "
                            "second neighbors. "
                            "This is achieved by checking how many second "
                            "neighbors would be added if one would connect to "
                            "the suggested node. A channel to the node "
                            "should get your node closer to "
                            "more other nodes.",
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser_recommend_nodes_second_neighbors.add_argument(
            '--nnodes', default=20, type=int,
            help='sets the number of nodes displayed')
        parser_recommend_nodes_second_neighbors.add_argument(
            '--sort-by', default='sec', type=str,
            help="sort by column [abbreviation, e.g. 'sec']")

        # cmd: report
        parser_report = subparsers.add_parser(
            'report',
            help="displays reports of activity on the node")
        parser_report.add_argument(
            '--from-days-ago', default=1, type=int,
            help='time interval start (days ago)')
        parser_report.add_argument(
            '--to-days-ago', default=0, type=int,
            help='time interval end (days ago)')

        # cmd: info
        parser_info = subparsers.add_parser(
            'info',
            help='displays info on channels and nodes')
        parser_info.add_argument(
            'info_string', type=str,
            help='info string can represent a node public key or a channel id')

        # cmd: lncli
        if self.lncli:
            parser_lncli = subparsers.add_parser(
            'lncli',
            help='execute lncli')

    def check_for_lncli(self):
        """
        Looks for lncli in PATH or in LNDMANAGE_HOME folder. Sets self.lncli
        and self.lncli_path. Executable in LNDMANAGE_HOME is prioritized.
        """
        lncli_candidate = os.path.join(settings.home_dir, 'lncli')

        # look in lndmanage home folder after lncli
        if os.access(lncli_candidate, os.X_OK):
            self.lncli = True
            self.lncli_path = lncli_candidate
        # look in PATH
        else:
            path = spawn.find_executable('lncli')
            self.lncli = True
            self.lncli_path = path

    def parse_arguments(self):
        return self.parser.parse_args()

    def run_commands(self, node, args):
        # program execution
        if args.loglevel:
            # update the loglevel of the stdout handler to the user choice
            logger.handlers[0].setLevel(args.loglevel)

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
                logger.info(
                    f"Forwardings from {args.from_days_ago} days ago"
                    f" to {args.to_days_ago} days ago are included.")
                listchannels.print_channels_forwardings(
                    time_interval_start=time_from, time_interval_end=time_to,
                    sort_string=args.sort_by)
            elif args.subcmd == 'hygiene':
                time_from = time.time() - args.from_days_ago * 24 * 60 * 60
                logger.info(f"Channel hygiene stats is over last "
                            f"{args.from_days_ago} days.")
                listchannels.print_channels_hygiene(
                    time_interval_start=time_from, sort_string=args.sort_by)

        elif args.cmd == 'rebalance':
            if args.target:
                logger.warning("Warning: Target is set, this is still an "
                               "experimental feature.")
            rebalancer = Rebalancer(node, args.max_fee_rate, args.max_fee_sat)
            try:
                rebalancer.rebalance(
                    args.channel,
                    dry=not args.reckless,
                    chunksize=args.chunksize,
                    target=args.target,
                    allow_unbalancing=args.allow_unbalancing,
                    strategy=args.strategy)
            except TooExpensive as e:
                logger.error(f"Too expensive: {e}")
            except RebalanceFailure as e:
                logger.error(f"Rebalance failure: {e}")

        elif args.cmd == 'circle':
            rebalancer = Rebalancer(node, args.max_fee_rate, args.max_fee_sat)
            invoice = node.get_rebalance_invoice(memo='circular payment')
            payment_hash, payment_address = invoice.r_hash, invoice.payment_addr
            try:
                rebalancer.rebalance_two_channels(
                    args.channel_from, args.channel_to,
                    args.amt_sat, payment_hash, payment_address,
                    args.max_fee_sat,
                    dry=not args.reckless)
            except DryRun:
                logger.info("This was just a dry run.")
            except TooExpensive:
                logger.error(
                    "Too expensive: consider to raise --max-fee-sat or "
                    "--max-fee-rate.")
            except RebalancingTrialsExhausted:
                logger.error(
                    f"Rebalancing trials exhausted (number of trials: "
                    f"{settings.REBALANCING_TRIALS}).")
            except PaymentTimeOut:
                logger.error("Payment failed because the payment timed out.")

        elif args.cmd == 'recommend-nodes':
            if not args.subcmd:
                self.parser_recommend_nodes.print_help()
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
            elif args.subcmd == 'second-neighbors':
                recommend_nodes.print_second_neighbors(
                    number_of_nodes=args.nnodes, sort_by=args.sort_by)

        elif args.cmd == 'report':
            time_from = time.time() - args.from_days_ago * 24 * 60 * 60
            time_to = time.time() - args.to_days_ago * 24 * 60 * 60
            report = Report(node, time_from, time_to)
            report.report()

        elif args.cmd == 'info':
            info = Info(node)
            info.parse_and_print(args.info_string)


def main():
    parser = Parser()

    # config.ini is expected to be in home/.lndmanage directory
    config_file = os.path.join(settings.home_dir, 'config.ini')

    # if lndmanage is run with arguments, run once
    if len(sys.argv) > 1:
        # take arguments from sys.argv
        args = parser.parse_arguments()
        node = LndNode(config_file=config_file)
        parser.run_commands(node, args)

    # otherwise enter an interactive mode
    else:
        history_file = os.path.join(settings.home_dir, "command_history")
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            # history will be written later
            pass

        logger.info("Running in interactive mode. "
                    "You can type 'help' or 'exit'.")
        node = LndNode(config_file=config_file)

        if parser.lncli:
            logger.info("Enabled lncli: using " + parser.lncli_path)

        while True:
            try:
                user_input = input("$ lndmanage ")
            except KeyboardInterrupt:
                logger.info("")
                continue
            except EOFError:
                readline.write_history_file(history_file)
                logger.info("exit")
                return 0

            if not user_input or user_input in ['help', '-h', '--help']:
                parser.parser.print_help()
                continue
            elif user_input == 'exit':
                readline.write_history_file(history_file)
                return 0

            args_list = user_input.split(" ")

            # lncli execution
            if args_list[0] == 'lncli':
                lncli = Lncli(parser.lncli_path, config_file)
                lncli.lncli(args_list[1:])
                continue
            try:
                # need to run with parse_known_args to get an exception
                args = parser.parser.parse_args(args_list)
                parser.run_commands(node, args)
            except SystemExit:
                # argparse may raise SystemExit on incorrect user input,
                # which is a graceful exit. The user gets the standard output
                # from argparse of what went wrong.
                continue


if __name__ == '__main__':
    main()

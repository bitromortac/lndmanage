"""
Module for printing lightning channels.
"""

import math
import logging
import time
from collections import OrderedDict

from lndmanage.lib.forwardings import get_forwarding_statistics_channels
from lndmanage import settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# define symbols for bool to string conversion
POSITIVE_MARKER = u"\u2713"
NEGATIVE_MARKER = u"\u2717"
ALIAS_LENGTH = 25
ANNOTATION_LENGTH = 25


# define printing abbreviations
# convert key can specify a function, which lets one do unit conversions
PRINT_CHANNELS_FORMAT = {
    'act': {
        'dict_key': 'active',
        'description': 'channel is active',
        'width': 3,
        'format': '^3',
        'align': '>',
        'convert': lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    'age': {
        'dict_key': 'age',
        'description': 'channel age [days]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'alias': {
        'dict_key': 'alias',
        'description': 'alias',
        'width': ALIAS_LENGTH,
        'format': '.<'+str(ALIAS_LENGTH),
        'align': '^',
        'convert': lambda x: alias_cutoff(x),
    },
    'annotation': {
        'dict_key': 'annotation',
        'description': 'channel annotation',
        'width': ANNOTATION_LENGTH,
        'format': '.<'+str(ANNOTATION_LENGTH),
        'align': '^',
        'convert': lambda x: alias_cutoff(x),
    },
    'atb': {
        'dict_key': 'amount_to_balanced',
        'description': 'amount to be balanced (local side) [sat]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'bwd': {
        'dict_key': 'bandwidth_demand',
        'description': 'bandwidth demand: capacity / max(mean_in, mean_out)',
        'width': 5,
        'format': '5.2f',
        'align': '>',
    },
    'cap': {
        'dict_key': 'capacity',
        'description': 'channel capacity [sat]',
        'width': 9,
        'format': '9d',
        'align': '>',
    },
    'cid': {
        'dict_key': 'chan_id',
        'description': 'channel id',
        'width': 18,
        'format': '',
        'align': '^',
    },
    'fees': {
        'dict_key': 'fees_total',
        'description': 'total fees [sat]',
        'width': 7,
        'format': '7.2f',
        'align': '>',
        'convert': lambda x: float(x) / 1000
    },
    'f/w': {
        'dict_key': 'fees_total_per_week',
        'description': 'total fees per week [sat / week]',
        'width': 6,
        'format': '6.2f',
        'align': '>',
        'convert': lambda x: float(x) / 1000
    },
    'flow': {
        'dict_key': 'flow_direction',
        'description': 'flow direction (positive is outwards)',
        'width': 5,
        'format': '5.2f',
        'align': '>',
        # 'convert': lambda x: '>'*int(nan_to_zero(x)*10/3.0) if x > 0 else
        # '<'*(-int(nan_to_zero(x)*10/3.0))
    },
    'pbf': {
        'dict_key': 'peer_base_fee',
        'description': 'peer base fee [msat]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'pfr': {
        'dict_key': 'peer_fee_rate',
        'description': 'peer fee rate',
        'width': 8,
        'format': '1.6f',
        'align': '>',
        'convert': lambda x: x / 1E6
    },
    'lbf': {
        'dict_key': 'local_base_fee',
        'description': 'local base fee [msat]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'lfr': {
        'dict_key': 'local_fee_rate',
        'description': 'local fee rate',
        'width': 8,
        'format': '1.6f',
        'align': '>',
        'convert': lambda x: x / 1E6
    },
    'lup': {
        'dict_key': 'last_update',
        'description': 'last update time [days ago]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'lupp': {
        'dict_key': 'last_update_peer',
        'description': 'last update time by peer [days ago]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'lupl': {
        'dict_key': 'last_update_local',
        'description': 'last update time by local [days ago]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'lb': {
        'dict_key': 'local_balance',
        'description': 'local balance [sat]',
        'width': 9,
        'format': '9d',
        'align': '>',
    },
    'nfwd': {
        'dict_key': 'number_forwardings',
        'description': 'number of forwardings',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'priv': {
        'dict_key': 'private',
        'description': 'channel is private',
        'width': 5,
        'format': '^5',
        'align': '>',
        'convert': lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    'r': {
        'dict_key': 'action_required',
        'description': 'action is required',
        'width': 1,
        'format': '^1',
        'align': '>',
        'convert': lambda x: NEGATIVE_MARKER if x else '',
    },
    'rb': {
        'dict_key': 'remote_balance',
        'description': 'remote balance [sat]',
        'width': 9,
        'format': '9d',
        'align': '>',
    },
    'in': {
        'dict_key': 'total_forwarding_in',
        'description': 'total forwarding inwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'ini': {
        'dict_key': 'initiator',
        'description': 'true if we opened channel',
        'width': 3,
        'format': '^3',
        'align': '>',
        'convert': lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    'tot': {
        'dict_key': 'total_forwarding',
        'description': 'total forwarding [sat]',
        'width': 5,
        'format': '5.0f',
        'align': '>',
    },
    'ub': {
        'dict_key': 'unbalancedness',
        'description': 'unbalancedness [-1 ... 1] (0 is 50:50 balanced)',
        'width': 5,
        'format': '5.2f',
        'align': '>',
    },
    'ulr': {
        'dict_key': 'uptime_lifetime_ratio',
        'description': 'ratio of uptime to lifetime of channel [0 ... 1]',
        'width': 5,
        'format': '5.2f',
        'align': '>',
    },
    'imed': {
        'dict_key': 'median_forwarding_in',
        'description': 'median forwarding inwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'imean': {
        'dict_key': 'mean_forwarding_in',
        'description': 'mean forwarding inwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'imax': {
        'dict_key': 'largest_forwarding_amount_in',
        'description': 'largest forwarding inwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'omed': {
        'dict_key': 'median_forwarding_out',
        'description': 'median forwarding outwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'omean': {
        'dict_key': 'mean_forwarding_out',
        'description': 'mean forwarding outwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'omax': {
        'dict_key': 'largest_forwarding_amount_out',
        'description': 'largest forwarding outwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'out': {
        'dict_key': 'total_forwarding_out',
        'description': 'total forwarding outwards [sat]',
        'width': 10,
        'format': '10.0f',
        'align': '>',
    },
    'sr/w': {
        'dict_key': 'sent_received_per_week',
        'description': 'sent and received per week [sat]',
        'width': 9,
        'format': '9d',
        'align': '>',
    },
}


def alias_cutoff(alias):
    """
    Cuts off the node alias at a certain length and removes unicode
    characters from the node alias.
    :param alias: str
    :return: str
    """
    if len(alias) > ALIAS_LENGTH:
        return alias[:ALIAS_LENGTH-3] + '...'
    else:
        return alias


class ListChannels(object):
    """
    A class to list lightning channels.
    """
    def __init__(self, node):
        """
        :param node: :class:`lib.node.Node`
        """
        self.node = node

    def print_all_channels(self, sort_string='rev_alias'):
        """
        Prints all active and inactive channels.

        :param sort_string: str
        """

        channels = self._add_channel_annotations(self.node.get_all_channels())

        sort_string, reverse_sorting = self._sorting_order(sort_string)
        sort_dict = {
            'function': lambda x: (
                x[1][PRINT_CHANNELS_FORMAT['priv']['dict_key']],
                x[1][sort_string]
                ),
            'string': sort_string,
            'reverse': reverse_sorting,
        }

        self._print_channels(
            channels, columns='cid,priv,act,ub,cap,lb,rb,lbf,'
                              'lfr,annotation,alias',
            sort_dict=sort_dict)

    def print_channels_unbalanced(self, unbalancedness, sort_string='rev_ub'):
        """
        Prints unbalanced channels with
        |unbalancedness(channel)| > unbalancedness.

        :param unbalancedness: float
        :param sort_string: str
        """

        channels = self._add_channel_annotations(
            self.node.get_unbalanced_channels(unbalancedness))

        sort_string, reverse_sorting = self._sorting_order(sort_string)
        sort_dict = {
            'function': lambda x: x[1][sort_string],
            'string': sort_string,
            'reverse': reverse_sorting,
        }

        self._print_channels(
            channels, columns='cid,ub,cap,lb,rb,pbf,pfr,annotation,alias',
            sort_dict=sort_dict)

    def print_channels_inactive(self, sort_string='lupp'):
        """
        Prints all inactive channels.

        :param sort_string: str
        """

        channels = self._add_channel_annotations(
            self.node.get_inactive_channels())

        sort_string, reverse_sorting = self._sorting_order(sort_string)
        sort_dict = {
            'function': lambda x: (-x[1]['private'], x[1][sort_string]),
            'string': sort_string,
            'reverse': reverse_sorting,
        }

        self._print_channels(
            channels, columns='cid,lupp,ulr,priv,ini,age,ub,cap,lb,rb,'
                              'sr/w,annotation,alias',
            sort_dict=sort_dict)

    def print_channels_forwardings(self, time_interval_start,
                                   time_interval_end, sort_string):

        """
        Prints forwarding statistics for each channel.

        :param time_interval_start: int
        :param time_interval_end: int
        :param sort_string: str
        """

        channels = get_forwarding_statistics_channels(
            self.node, time_interval_start, time_interval_end)

        channels = self._add_channel_annotations(channels)

        sort_string, reverse_sorting = self._sorting_order(sort_string)
        sort_dict = {
            'function': lambda x: (
                float('inf') if math.isnan(x[1][sort_string])
                else x[1][sort_string],
                x[1][PRINT_CHANNELS_FORMAT['nfwd']['dict_key']],
                x[1][PRINT_CHANNELS_FORMAT['ub']['dict_key']]
                ),
            'string': sort_string,
            'reverse': reverse_sorting,
        }

        self._print_channels(
            channels,
            columns='cid,nfwd,age,fees,f/w,flow,ub,bwd,r,'
                    'cap,pbf,pfr,annotation,alias',
            sort_dict=sort_dict)

    def print_channels_hygiene(self, time_interval_start, sort_string):
        """
        Prints hygiene statistics for each channel.

        :param time_interval_start: int
        :param time_interval_end: int
        :param sort_string: str
        """
        time_interval_end = time.time()
        channels = get_forwarding_statistics_channels(
            self.node, time_interval_start, time_interval_end)

        channels = self._add_channel_annotations(channels)

        sort_string, reverse_sorting = self._sorting_order(sort_string)
        sort_dict = {
            'function': lambda x:
                x[1][sort_string],
            'string': sort_string,
            'reverse': reverse_sorting,
        }

        self._print_channels(
            channels,
            columns='cid,age,nfwd,f/w,ulr,lb,cap,pbf,pfr,annotation,alias',
            sort_dict=sort_dict)

    def _add_channel_annotations(self, channels):
        """
        Appends metadata to existing channel dicts from the configuration file.

        :param channels: dict
        :return: dict
        """
        logger.debug("Adding annotations from file %s.", self.node.config_file)
        # mapping between the channel point and channel id
        channel_point_mapping = {k: v['channel_point'].split(':')[0]
                                 for k, v in channels.items()}
        # only read annotations if config file is given
        if self.node.config_file:
            config = settings.read_config(self.node.config_file)
            annotations = config['annotations']
        else:
            annotations = {}
        channel_annotations_funding_id = {}
        channel_annotations_channel_id = {}

        for id, annotation in annotations.items():
            if len(id) == 18 and id.isnumeric():
                # valid channel id
                channel_annotations_channel_id[int(id)] = \
                    annotation
            elif len(id) == 64 and id.isalnum():
                # valid funding transaction id
                channel_annotations_funding_id[id] = \
                    annotation
            else:
                raise ValueError(
                    'First part needs to be either a channel id or the '
                    'funding transaction id. \n'
                    'The funding transaction id can be found with '
                    '`lncli listchannels` under the channel point (the '
                    'characters before the colon).'
                )

        for channel_id, channel_values in channels.items():
            # get the annotation by channel id first
            annotation = channel_annotations_channel_id.get(channel_id, None)
            # if no channel annotation, try with funding id
            if annotation is None:
                annotation = channel_annotations_funding_id.get(
                    channel_point_mapping[channel_id], None)

            if annotation is not None:
                channels[channel_id]['annotation'] = annotation
            else:
                channels[channel_id]['annotation'] = ''

        return channels

    def _print_channels(self, channels, columns, sort_dict):
        """
        General purpose channel printing.

        :param channels: dict
        :param columns: str
        :param sort_dict: dict
        """

        if not channels:
            logger.info(">>> Did not find any channels.")

        channels = OrderedDict(sorted(
            channels.items(), key=sort_dict['function'],
            reverse=sort_dict['reverse']))

        logger.info("Sorting channels by %s.", sort_dict['string'])

        logger.info("-------- Description --------")
        columns = columns.split(',')
        for column in columns:
            logger.info(
                "%-10s %s", column,
                PRINT_CHANNELS_FORMAT[column]['description'])

        logger.info("-------- Channels --------")
        # prepare the column header
        column_header = ''
        for column in columns:
            column_label = PRINT_CHANNELS_FORMAT[column]['align']
            column_width = PRINT_CHANNELS_FORMAT[column]['width']
            column_header += f"{column:{column_label}{column_width}} "

        # print the channel data
        for channel_number, (_, channel_data) in enumerate(channels.items()):
            if not channel_number % 20:
                logger.info(column_header)
            row = self._row_string(channel_data, columns)
            logger.info(row)

    @staticmethod
    def _row_string(column_values, columns):
        """
        Constructs the formatted row string for table printing.

        :param column_values: dict
        :param columns: list of str
        :return: formatted str
        """

        string = ''
        for column in columns:
            format_string = PRINT_CHANNELS_FORMAT[column]['format']
            conversion_function = PRINT_CHANNELS_FORMAT[column].get(
                'convert', lambda x: x)
            value = column_values[PRINT_CHANNELS_FORMAT[column]['dict_key']]
            converted_value = conversion_function(value)
            string += f"{converted_value:{format_string}} "

        return string

    @staticmethod
    def _sorting_order(sort_string):
        """
        Determines the sorting string and the sorting order.

        If sort_string starts with 'rev_', the sorting order is reversed.

        :param sort_string: str
        :return: bool
        """

        reverse_sorting = True
        if sort_string[:4] == 'rev_':
            reverse_sorting = False
            sort_string = sort_string[4:]

        sort_string = PRINT_CHANNELS_FORMAT[sort_string]['dict_key']

        return sort_string, reverse_sorting

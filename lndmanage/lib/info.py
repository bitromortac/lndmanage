import re
import datetime

from lndmanage.lib.network_info import NetworkAnalysis
from lndmanage.lib import ln_utilities
from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# width of a column in the ouptput in characters
COL_WIDTH = 66


def padded_column_string(string1, string2, unit, shift=10, max_len_string1=25):
    """
    Padded_column_string is a helper function which returns a formatted string
    representing object, quantity and unit of a piece of information.

    :param string1: information
    :type string1: str
    :param string2: quantity
    :type string2: str
    :param unit: unit of the information
    :type unit: str
    :param shift: whitespace shift to the right (indentation)
    :type shift: int
    :param max_len_string1: needed to calculate padding to the right
    :type max_len_string1: int
    :return:
    :rtype:
    """

    string = f" " * shift + f"{string1:<{max_len_string1}} {string2} {unit}"
    if type(string2) == float:
        string = f" " * shift + f"{string1:<{max_len_string1}} " \
            f"{string2:0.6f} {unit}"
    return string


class Info(object):
    """
    Implements the info command, which displays info on individual channels and
    nodes.
    """
    def __init__(self, node):
        """
        :param node: node object
        :type node: lndmanage.lib.node.LndNode
        """
        self.node = node
        self.network_info = NetworkAnalysis(self.node)

    def parse_and_print(self, info):
        """
        Parses an info string for a channel id or node public key and prints
        out the information gathered about the object.

        :param info: channel id or node public key
        :type info: str
        """

        # analyzer = NetworkAnalysis(self.node)
        try:
            channel_id, node_pub_key = self.parse(info)
        except ValueError:
            logger.info("Info didn't represent neither a channel nor a node.")
            return

        # Info was a channel.
        if channel_id is not None:
            try:
                general_info = self.node.network.edges[channel_id]
            except KeyError:
                logger.info("Channel id %s is not known in the public graph.",
                            channel_id)
                return

            # Add some more information on the channel.
            general_info['node1_alias'] = \
                self.node.network.node_alias(general_info['node1_pub'])
            general_info['node2_alias'] = \
                self.node.network.node_alias(general_info['node2_pub'])
            general_info['blockheight'] = \
                ln_utilities.convert_channel_id_to_short_channel_id(
                    channel_id)[0]
            general_info['open_timestamp'] = ln_utilities.height_to_timestamp(
                self.node, general_info['blockheight'])

            # TODO: if it's our channel, add extra info
            extra_info = None

            self.print_channel_info(general_info)

        # Info was a node.
        else:
            try:
                general_info = self.network_info.node_info_basic(node_pub_key)
            except KeyError:
                return

            # TODO: if it's a (channel) peer or our node, add extra info
            extra_info = None

            self.print_node_info(general_info)

    def parse(self, info):
        """
        Parse whether info contains a channel id or node public key and hand
        it back. If no info could be extracted, raise a ValueError.

        :param info:
        :type info: str
        :return: channel_id, node_pub_key
        :rtype: int, str
        """
        exp_channel_id = re.compile("^[0-9]{18}$")
        exp_short_channel_id = re.compile("^[0-9]{6}x[0-9]{3}x[0-9]$")
        exp_chan_point = re.compile("^[a-z0-9]{64}:[0-9]$")
        exp_node_id = re.compile("^[a-z0-9]{66}$")

        channel_id = None
        node_pub_key = None

        # prepare input string info
        if exp_channel_id.match(info) is not None:
            logger.debug("Info represents channel id.")
            channel_id = int(info)
        elif exp_short_channel_id.match(info) is not None:
            logger.debug("Info represents short channel id.")
            # TODO: convert short channel id to channel id
            channel_id = 0
        elif exp_chan_point.match(info) is not None:
            # TODO: convert chan point to channel id
            logger.debug("Info represents short channel id.")
            channel_id = 0
        elif exp_node_id.match(info) is not None:
            logger.debug("Info represents node public key.")
            node_pub_key = info
        else:
            raise ValueError("Info string doesn't match any pattern.")

        return channel_id, node_pub_key

    def print_channel_info(self, general_info):
        """
        Prints the channel info with peer information.

        :param general_info: information about the channel in the public graph
        :type general_info: dict
        """

        logger.info("-------- Channel info --------")
        logger.info(f"channel id: {general_info['channel_id']}  "
                    f"channel point: {general_info['chan_point']}")

        # capactiy
        string = padded_column_string(
            'capacity:', general_info['capacity'], 'sat')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # blockheight
        string = padded_column_string(
            'blockheight:', general_info['blockheight'], '')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # opening time
        time = datetime.datetime.utcfromtimestamp(
            general_info['open_timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        string = padded_column_string('open since:', time, '')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # channel age
        age = round(
            (self.node.blockheight - general_info['blockheight']) / 6 / 24, 2)
        string = padded_column_string('channel age:', age, 'days')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # last update
        last_update = general_info['last_update']
        last_update_time = datetime.datetime.utcfromtimestamp(
            last_update).strftime('%Y-%m-%d %H:%M:%S')
        string = padded_column_string('last update:', last_update_time, '')
        logger.info(f"{string:{COL_WIDTH*2}}")
        logger.info("")

        # channel partner overview
        logger.info("-------- Channel partners --------")
        logger.info(f"{general_info['node1_pub']:{COL_WIDTH}} | "
                    f"{general_info['node2_pub']:{COL_WIDTH}}")
        logger.info(f"{general_info['node1_alias']:^{COL_WIDTH}} | "
                    f"{general_info['node2_alias']:^{COL_WIDTH}}")

        np1 = general_info['node1_policy']
        np2 = general_info['node2_policy']
        last_update_1 = np1['last_update']
        last_update_2 = np2['last_update']

        last_update_time_1 = datetime.datetime.utcfromtimestamp(
            last_update_1).strftime('%Y-%m-%d %H:%M:%S')
        last_update_time_2 = datetime.datetime.utcfromtimestamp(
            last_update_2).strftime('%Y-%m-%d %H:%M:%S')

        # base fee
        string_left = padded_column_string(
            'base fee:', np1['fee_base_msat'], 'msat')
        string_right = padded_column_string(
            'base fee:', np2['fee_base_msat'], 'msat')
        logger.info(
            f"{string_left:{COL_WIDTH}} | {string_right:{COL_WIDTH}}")

        # fee rate
        string_left = padded_column_string(
            'fee rate:', np1['fee_rate_milli_msat'] / 1E6, 'sat/sat')
        string_right = padded_column_string(
            'fee rate:', np2['fee_rate_milli_msat'] / 1E6, 'sat/sat')
        logger.info(
            f"{string_left:{COL_WIDTH}} | {string_right:{COL_WIDTH}}")

        # time lock delta
        string_left = padded_column_string(
            'time lock delta:', np1['time_lock_delta'], 'blocks')
        string_right = padded_column_string(
            'time lock delta:', np2['time_lock_delta'], 'blocks')
        logger.info(
            f"{string_left:{COL_WIDTH}} | {string_right:{COL_WIDTH}}")

        # disabled
        string_left = padded_column_string('disabled:', np1['disabled'], '')
        string_right = padded_column_string('disabled:', np2['disabled'], '')
        logger.info(
            f"{string_left:{COL_WIDTH}} | {string_right:{COL_WIDTH}}")

        # last update
        string_left = padded_column_string(
            'last update:', last_update_time_1, '')
        string_right = padded_column_string(
            'last update:', last_update_time_2, '')
        logger.info(
            f"{string_left:{COL_WIDTH}} | {string_right:{COL_WIDTH}}")

    def print_node_info(self, general_info):
        """
        Prints the node info.

        :param general_info: information about the node in the public graph
        :type general_info: dict
        """
        logger.info("-------- Node info --------")
        logger.info(general_info['pub_key'])

        # alias
        string = padded_column_string('alias:', general_info['alias'], '')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # last update
        last_update = general_info['last_update']
        last_update_time = datetime.datetime.utcfromtimestamp(
            last_update).strftime('%Y-%m-%d %H:%M:%S')
        string = padded_column_string('last update:', last_update_time, '')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # numer of channels
        string = padded_column_string(
            'number of channels:', general_info['num_channels'], '')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # total capacity
        string = padded_column_string(
            'total capacity:', general_info['total_capacity'], 'sat')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # capacity per channel
        string = padded_column_string(
            'capacity (median):', general_info['median_capacity'], 'sat')
        logger.info(f"{string:{COL_WIDTH*2}}")
        string = padded_column_string(
            'capacity (mean):', general_info['mean_capacity'], 'sat')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # fees
        string = padded_column_string(
            'base fee (median):', general_info['median_base_fee'], 'msat')
        logger.info(f"{string:{COL_WIDTH*2}}")
        string = padded_column_string(
            'base fee (mean):', general_info['mean_base_fee'], 'msat')
        logger.info(f"{string:{COL_WIDTH*2}}")
        string = padded_column_string(
            'fee rate (median):', general_info['median_fee_rate'], 'sat/sat')
        logger.info(f"{string:{COL_WIDTH*2}}")
        string = padded_column_string(
            'fee rate (mean):', general_info['mean_fee_rate'], 'sat/sat')
        logger.info(f"{string:{COL_WIDTH*2}}")

        # addresses
        logger.info("-------- Addresses --------")
        for addr in general_info['addresses']:
            logger.info(5 * " " + general_info['pub_key'] + "@" + addr)

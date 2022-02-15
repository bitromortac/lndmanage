"""Contains Lightning network specific conversion utilities."""
from typing import Tuple

import re
import time

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def convert_short_channel_id_to_channel_id(blockheight, transaction, output):
    """
    Converts short channel id (blockheight:transaction:output) to a long integer channel id.

    :param blockheight:
    :param transaction: Number of transaction in the block.
    :param output: Number of output in the transaction.
    :return: channel id: Encoded integer number representing the channel,
     can be decoded by :func:`lib.conversion.extract_short_channel_id_from_string`.
    """
    return blockheight << 40 | transaction << 16 | output


def convert_channel_id_to_short_channel_id(channel_id):
    """
    Converts a channel id to blockheight, transaction, output
    """
    return channel_id >> 40, channel_id >> 16 & 0xFFFFFF, channel_id & 0xFFFF


def extract_short_channel_id_from_string(string):
    """
    Parses a payment error message for the short channel id of the form XXXX:XXXX:XXX.

    :param string:
    :return: short channel id [blockheight, transaction, output]
    """
    match = re.search(r'[0-9]+:[0-9]+:[0-9]+', string)
    group = match.group()
    groups = list(map(int, group.split(':')))
    assert len(groups) == 3
    return groups


def local_balance_to_unbalancedness(local_balance: int, capacity: int, commit_fee: int,
                                    initiator: bool) -> Tuple[float, int]:
    """Calculates the unbalancedness.

    :return: float:
        in [-1.0, 1.0]
    """
    # inverse of the formula:
    commit_fee = 0 if not initiator else commit_fee
    return -(2 * (local_balance + commit_fee) / capacity - 1), commit_fee


def unbalancedness_to_local_balance(unbalancedness: float, capacity: int, commit_fee: int, initiator: bool) -> Tuple[int, int]:
    commit_fee = 0 if not initiator else commit_fee
    return -int(capacity * (unbalancedness - 1) / 2) - commit_fee, commit_fee


def height_to_timestamp(node, close_height):
    now = time.time()
    blocks_ago = node.blockheight - close_height
    time_ago = blocks_ago * 10 * 60
    timestamp_sec = int(now - time_ago)
    return timestamp_sec


def parse_nodeid_channelid(info: str) -> Tuple[int, str]:
    """Parse whether info contains a channel id or node public key and hand
    it back. If no info could be extracted, raise a ValueError.

    :return: channel_id, node_pub_key
    """
    exp_channel_id = re.compile("^[0-9]{13,20}$")
    exp_short_channel_id = re.compile("^[0-9]{6}x[0-9]{3}x[0-9]$")
    exp_chan_point = re.compile("^[a-z0-9]{64}:[0-9]$")
    exp_node_id = re.compile("^[a-z0-9]{66}$")

    channel_id = None
    node_pub_key = None

    # prepare input string info
    info = str(info)
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
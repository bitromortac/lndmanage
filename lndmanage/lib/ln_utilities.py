"""Contains Lightning network specific conversion utilities."""

import re
import time


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


def channel_unbalancedness_and_commit_fee(local_balance, capacity, commit_fee,
                                          initiator):
    """
    Calculates the unbalancedness.

    :param local_balance: int
    :param capacity: int
    :param commit_fee: int
    :param initiator: bool
    :return: float:
        in [-1.0, 1.0]
    """
    # inverse of the formula:
    # c.local_balance = c.capacity * 0.5 * (-unbalancedness + 1) - commit_fee
    commit_fee = 0 if not initiator else commit_fee
    return -(2 * float(local_balance + commit_fee) / capacity - 1), commit_fee


def height_to_timestamp(node, close_height):
    now = time.time()
    blocks_ago = node.blockheight - close_height
    time_ago = blocks_ago * 10 * 60
    timestamp_sec = int(now - time_ago)
    return timestamp_sec
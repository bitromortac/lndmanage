"""Contains Lightning network specific conversion utilities."""

import re


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

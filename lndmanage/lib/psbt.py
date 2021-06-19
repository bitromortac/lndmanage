"""PSBT (BIP 174) utilities.
https://github.com/bitcoin/bips/blob/master/bip-0174.mediawiki
Sources:
https://github.com/Jason-Les/python-psbt
Programming Bitcoin book, Jimmy Song
"""
from io import BytesIO
from typing import List, Tuple, Optional

PSBT_MAGIC_SEPARATOR = b'psbt' + b'\xFF'
PSBT_GLOBAL_UNSIGNED_TX = b'\x00'


def little_endian_to_int(b: bytes):
    '''little_endian_to_int takes bytes sequence as a little-endian number.
    Returns an integer'''
    # use the from_bytes method of int
    return int.from_bytes(b, 'little')


def read_varint(s: BytesIO):
    '''read_varint reads a variable integer from a stream'''
    i = s.read(1)[0]
    if i == 0xfd:
        # 0xfd means the next two bytes are the number
        return little_endian_to_int(s.read(2))
    elif i == 0xfe:
        # 0xfe means the next four bytes are the number
        return little_endian_to_int(s.read(4))
    elif i == 0xff:
        # 0xff means the next eight bytes are the number
        return little_endian_to_int(s.read(8))
    else:
        # anything else is just the integer
        return i


def parse_key_value(stream: BytesIO) -> Tuple[Optional[bytes], Optional[bytes]]:
    key_length = read_varint(stream)
    # a key length of 0 represents a separator
    if key_length == 0:
        return None, None
    key = stream.read(key_length)
    val_length = read_varint(stream)
    val = stream.read(val_length)
    return key, val


def extract_psbt_inputs_outputs(psbt: bytes) -> Tuple[int, int, List[int]]:
    """Parses only the transaction in the global map of a PSBT representing
    an unsigned transaction and returns the number of inputs, outputs, and the
    individual amounts."""
    stream = BytesIO(psbt)
    # parse header
    header = stream.read(5)
    if header != PSBT_MAGIC_SEPARATOR:
        raise ValueError("wrong psbt header")

    # parse global
    key, value = parse_key_value(stream)
    if key != PSBT_GLOBAL_UNSIGNED_TX:
        raise NotImplementedError("Can't parse PSBTs that contain other data than unsigned transactions.")

    # parse transaction
    transaction_stream = BytesIO(value)
    version = little_endian_to_int(transaction_stream.read(4))

    # parse inputs
    num_inputs = read_varint(transaction_stream)
    for _ in range(num_inputs):
        prev_tx = transaction_stream.read(32)[::-1]
        prev_index = little_endian_to_int(transaction_stream.read(4))
        script_sig_length = read_varint(transaction_stream)
        script_sig = transaction_stream.read(script_sig_length)
        sequence = little_endian_to_int(transaction_stream.read(4))

    # parse outputs
    num_outputs = read_varint(transaction_stream)
    output_amounts = []
    for _ in range(num_outputs):
        amount = little_endian_to_int(transaction_stream.read(8))
        script_pubkey_length = read_varint(transaction_stream)
        script_pubkey = transaction_stream.read(script_pubkey_length)
        output_amounts.append(amount)
    return num_inputs, num_outputs, output_amounts

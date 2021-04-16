import random
import time
import enum
import re
from enum import Enum, IntFlag
from typing import NamedTuple, Optional, Sequence, Dict, Set
from decimal import Decimal
from collections import defaultdict
from binascii import hexlify
from hashlib import sha256

import bitstring

TOTAL_COIN_SUPPLY_LIMIT_IN_BTC = 21000000
COIN = 100000000

BECH32_CONST = 1
BECH32M_CONST = 0x2bc830a3


CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CHARSET_INVERSE = {x: CHARSET.find(x) for x in CHARSET}

SEGWIT_HRP = "bc"


def bech32_polymod(values):
    """Internal function that computes the Bech32 checksum."""
    generator = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def bech32_hrp_expand(hrp):
    """Expand the HRP into values for checksum computation."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_verify_checksum(hrp, data):
    """Verify a checksum given HRP and converted data characters."""
    check = bech32_polymod(bech32_hrp_expand(hrp) + data)
    if check == BECH32_CONST:
        return Encoding.BECH32
    elif check == BECH32M_CONST:
        return Encoding.BECH32M
    else:
        return None

class Encoding(Enum):
    """Enumeration type to list the various supported encodings."""
    BECH32 = 1
    BECH32M = 2


class DecodedBech32(NamedTuple):
    encoding: Optional[Encoding]
    hrp: Optional[str]
    data: Optional[Sequence[int]]  # 5-bit ints


def bech32_decode(bech: str, *, ignore_long_length=False) -> DecodedBech32:
    """Validate a Bech32/Bech32m string, and determine HRP and data."""
    bech_lower = bech.lower()
    if bech_lower != bech and bech.upper() != bech:
        return DecodedBech32(None, None, None)
    pos = bech.rfind('1')
    if pos < 1 or pos + 7 > len(bech) or (not ignore_long_length and len(bech) > 90):
        return DecodedBech32(None, None, None)
    # check that HRP only consists of sane ASCII chars
    if any(ord(x) < 33 or ord(x) > 126 for x in bech[:pos+1]):
        return DecodedBech32(None, None, None)
    bech = bech_lower
    hrp = bech[:pos]
    try:
        data = [_CHARSET_INVERSE[x] for x in bech[pos+1:]]
    except KeyError:
        return DecodedBech32(None, None, None)
    encoding = bech32_verify_checksum(hrp, data)
    if encoding is None:
        return DecodedBech32(None, None, None)
    return DecodedBech32(encoding=encoding, hrp=hrp, data=data[:-6])

class LnFeatureContexts(enum.Flag):
    INIT = enum.auto()
    NODE_ANN = enum.auto()
    CHAN_ANN_AS_IS = enum.auto()
    CHAN_ANN_ALWAYS_ODD = enum.auto()
    CHAN_ANN_ALWAYS_EVEN = enum.auto()
    INVOICE = enum.auto()


LNFC = LnFeatureContexts

_ln_feature_direct_dependencies = defaultdict(set)  # type: Dict[LnFeatures, Set[LnFeatures]]
_ln_feature_contexts = {}  # type: Dict[LnFeatures, LnFeatureContexts]


def list_enabled_bits(x: int) -> Sequence[int]:
    """e.g. 77 (0b1001101) --> (0, 2, 3, 6)"""
    binary = bin(x)[2:]
    rev_bin = reversed(binary)
    return tuple(i for i, b in enumerate(rev_bin) if b == '1')


def get_ln_flag_pair_of_bit(flag_bit: int) -> int:
    """Ln Feature flags are assigned in pairs, one even, one odd. See BOLT-09.
    Return the other flag from the pair.
    e.g. 6 -> 7
    e.g. 7 -> 6
    """
    if flag_bit % 2 == 0:
        return flag_bit + 1
    else:
        return flag_bit - 1


class LnFeatures(IntFlag):
    OPTION_DATA_LOSS_PROTECT_REQ = 1 << 0
    OPTION_DATA_LOSS_PROTECT_OPT = 1 << 1
    _ln_feature_contexts[OPTION_DATA_LOSS_PROTECT_OPT] = (LNFC.INIT | LnFeatureContexts.NODE_ANN)
    _ln_feature_contexts[OPTION_DATA_LOSS_PROTECT_REQ] = (LNFC.INIT | LnFeatureContexts.NODE_ANN)

    INITIAL_ROUTING_SYNC = 1 << 3
    _ln_feature_contexts[INITIAL_ROUTING_SYNC] = LNFC.INIT

    OPTION_UPFRONT_SHUTDOWN_SCRIPT_REQ = 1 << 4
    OPTION_UPFRONT_SHUTDOWN_SCRIPT_OPT = 1 << 5
    _ln_feature_contexts[OPTION_UPFRONT_SHUTDOWN_SCRIPT_OPT] = (LNFC.INIT | LNFC.NODE_ANN)
    _ln_feature_contexts[OPTION_UPFRONT_SHUTDOWN_SCRIPT_REQ] = (LNFC.INIT | LNFC.NODE_ANN)

    GOSSIP_QUERIES_REQ = 1 << 6
    GOSSIP_QUERIES_OPT = 1 << 7
    _ln_feature_contexts[GOSSIP_QUERIES_OPT] = (LNFC.INIT | LNFC.NODE_ANN)
    _ln_feature_contexts[GOSSIP_QUERIES_REQ] = (LNFC.INIT | LNFC.NODE_ANN)

    VAR_ONION_REQ = 1 << 8
    VAR_ONION_OPT = 1 << 9
    _ln_feature_contexts[VAR_ONION_OPT] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)
    _ln_feature_contexts[VAR_ONION_REQ] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)

    GOSSIP_QUERIES_EX_REQ = 1 << 10
    GOSSIP_QUERIES_EX_OPT = 1 << 11
    _ln_feature_direct_dependencies[GOSSIP_QUERIES_EX_OPT] = {GOSSIP_QUERIES_OPT}
    _ln_feature_contexts[GOSSIP_QUERIES_EX_OPT] = (LNFC.INIT | LNFC.NODE_ANN)
    _ln_feature_contexts[GOSSIP_QUERIES_EX_REQ] = (LNFC.INIT | LNFC.NODE_ANN)

    OPTION_STATIC_REMOTEKEY_REQ = 1 << 12
    OPTION_STATIC_REMOTEKEY_OPT = 1 << 13
    _ln_feature_contexts[OPTION_STATIC_REMOTEKEY_OPT] = (LNFC.INIT | LNFC.NODE_ANN)
    _ln_feature_contexts[OPTION_STATIC_REMOTEKEY_REQ] = (LNFC.INIT | LNFC.NODE_ANN)

    PAYMENT_SECRET_REQ = 1 << 14
    PAYMENT_SECRET_OPT = 1 << 15
    _ln_feature_direct_dependencies[PAYMENT_SECRET_OPT] = {VAR_ONION_OPT}
    _ln_feature_contexts[PAYMENT_SECRET_OPT] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)
    _ln_feature_contexts[PAYMENT_SECRET_REQ] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)

    BASIC_MPP_REQ = 1 << 16
    BASIC_MPP_OPT = 1 << 17
    _ln_feature_direct_dependencies[BASIC_MPP_OPT] = {PAYMENT_SECRET_OPT}
    _ln_feature_contexts[BASIC_MPP_OPT] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)
    _ln_feature_contexts[BASIC_MPP_REQ] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)

    OPTION_SUPPORT_LARGE_CHANNEL_REQ = 1 << 18
    OPTION_SUPPORT_LARGE_CHANNEL_OPT = 1 << 19
    _ln_feature_contexts[OPTION_SUPPORT_LARGE_CHANNEL_OPT] = (LNFC.INIT | LNFC.NODE_ANN)
    _ln_feature_contexts[OPTION_SUPPORT_LARGE_CHANNEL_REQ] = (LNFC.INIT | LNFC.NODE_ANN)

    OPTION_TRAMPOLINE_ROUTING_REQ = 1 << 24
    OPTION_TRAMPOLINE_ROUTING_OPT = 1 << 25

    _ln_feature_contexts[OPTION_TRAMPOLINE_ROUTING_REQ] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)
    _ln_feature_contexts[OPTION_TRAMPOLINE_ROUTING_OPT] = (LNFC.INIT | LNFC.NODE_ANN | LNFC.INVOICE)

    # temporary
    OPTION_TRAMPOLINE_ROUTING_REQ_ECLAIR = 1 << 50
    OPTION_TRAMPOLINE_ROUTING_OPT_ECLAIR = 1 << 51

    def validate_transitive_dependencies(self) -> bool:
        # for all even bit set, set corresponding odd bit:
        features = self  # copy
        flags = list_enabled_bits(features)
        for flag in flags:
            if flag % 2 == 0:
                features |= 1 << get_ln_flag_pair_of_bit(flag)
        # Check dependencies. We only check that the direct dependencies of each flag set
        # are satisfied: this implies that transitive dependencies are also satisfied.
        flags = list_enabled_bits(features)
        for flag in flags:
            for dependency in _ln_feature_direct_dependencies[1 << flag]:
                if not (dependency & features):
                    return False
        return True

    def for_init_message(self) -> 'LnFeatures':
        features = LnFeatures(0)
        for flag in list_enabled_bits(self):
            if LnFeatureContexts.INIT & _ln_feature_contexts[1 << flag]:
                features |= (1 << flag)
        return features

    def for_node_announcement(self) -> 'LnFeatures':
        features = LnFeatures(0)
        for flag in list_enabled_bits(self):
            if LnFeatureContexts.NODE_ANN & _ln_feature_contexts[1 << flag]:
                features |= (1 << flag)
        return features

    def for_invoice(self) -> 'LnFeatures':
        features = LnFeatures(0)
        for flag in list_enabled_bits(self):
            if LnFeatureContexts.INVOICE & _ln_feature_contexts[1 << flag]:
                features |= (1 << flag)
        return features

    def for_channel_announcement(self) -> 'LnFeatures':
        features = LnFeatures(0)
        for flag in list_enabled_bits(self):
            ctxs = _ln_feature_contexts[1 << flag]
            if LnFeatureContexts.CHAN_ANN_AS_IS & ctxs:
                features |= (1 << flag)
            elif LnFeatureContexts.CHAN_ANN_ALWAYS_EVEN & ctxs:
                if flag % 2 == 0:
                    features |= (1 << flag)
            elif LnFeatureContexts.CHAN_ANN_ALWAYS_ODD & ctxs:
                if flag % 2 == 0:
                    flag = get_ln_flag_pair_of_bit(flag)
                features |= (1 << flag)
        return features

    def supports(self, feature: 'LnFeatures') -> bool:
        """Returns whether given feature is enabled.

        Helper function that tries to hide the complexity of even/odd bits.
        For example, instead of:
          bool(myfeatures & LnFeatures.VAR_ONION_OPT or myfeatures & LnFeatures.VAR_ONION_REQ)
        you can do:
          myfeatures.supports(LnFeatures.VAR_ONION_OPT)
        """
        enabled_bits = list_enabled_bits(feature)
        if len(enabled_bits) != 1:
            raise ValueError(f"'feature' cannot be a combination of features: {feature}")
        flag = enabled_bits[0]
        our_flags = set(list_enabled_bits(self))
        return (flag in our_flags
                or get_ln_flag_pair_of_bit(flag) in our_flags)

class LnAddr(object):
    def __init__(self, *, paymenthash: bytes = None, amount=None, currency=None, tags=None, date=None,
                 payment_secret: bytes = None):
        self.date = int(time.time()) if not date else int(date)
        self.tags = [] if not tags else tags
        self.unknown_tags = []
        self.paymenthash = paymenthash
        self.payment_secret = payment_secret
        self.signature = None
        self.pubkey = None
        self.currency = SEGWIT_HRP if currency is None else currency
        self._amount = amount  # type: Optional[Decimal]  # in bitcoins
        self._min_final_cltv_expiry = 18

    @property
    def amount(self) -> Optional[Decimal]:
        return self._amount

    @amount.setter
    def amount(self, value):
        if not (isinstance(value, Decimal) or value is None):
            raise ValueError(f"amount must be Decimal or None, not {value!r}")
        if value is None:
            self._amount = None
            return
        assert isinstance(value, Decimal)
        if value.is_nan() or not (0 <= value <= TOTAL_COIN_SUPPLY_LIMIT_IN_BTC):
            raise ValueError(f"amount is out-of-bounds: {value!r} BTC")
        if value * 10**12 % 10:
            # max resolution is millisatoshi
            raise ValueError(f"Cannot encode {value!r}: too many decimal places")
        self._amount = value

    def get_amount_sat(self) -> Optional[Decimal]:
        # note that this has msat resolution potentially
        if self.amount is None:
            return None
        return self.amount * COIN

    def get_routing_info(self, tag):
        # note: tag will be 't' for trampoline
        r_tags = list(filter(lambda x: x[0] == tag, self.tags))
        # strip the tag type, it's implicitly 'r' now
        r_tags = list(map(lambda x: x[1], r_tags))
        # if there are multiple hints, we will use the first one that works,
        # from a random permutation
        random.shuffle(r_tags)
        return r_tags

    def get_amount_msat(self) -> Optional[int]:
        if self.amount is None:
            return None
        return int(self.amount * COIN * 1000)

    def get_features(self) -> 'LnFeatures':
        return LnFeatures(self.get_tag('9') or 0)

    def __str__(self):
        return "LnAddr[{}, amount={}{} tags=[{}]]".format(
            hexlify(self.pubkey.serialize()).decode('utf-8') if self.pubkey else None,
            self.amount, self.currency,
            ", ".join([k + '=' + str(v) for k, v in self.tags])
        )

    def get_min_final_cltv_expiry(self) -> int:
        return self._min_final_cltv_expiry

    def get_tag(self, tag):
        for k, v in self.tags:
            if k == tag:
                return v
        return None

    def get_description(self) -> str:
        return self.get_tag('d') or ''

    def get_expiry(self) -> int:
        exp = self.get_tag('x')
        if exp is None:
            exp = 3600
        return int(exp)

    def is_expired(self) -> bool:
        now = time.time()
        # BOLT-11 does not specify what expiration of '0' means.
        # we treat it as 0 seconds here (instead of never)
        return now > self.get_expiry() + self.date

_INT_TO_BINSTR = {a: '0' * (5-len(bin(a)[2:])) + bin(a)[2:] for a in range(32)}


# Bech32 spits out array of 5-bit values.  Shim here.
def u5_to_bitarray(arr):
    b = ''.join(_INT_TO_BINSTR[a] for a in arr)
    return bitstring.BitArray(bin=b)


def unshorten_amount(amount) -> Decimal:
    """ Given a shortened amount, convert it into a decimal
    """
    # BOLT #11:
    # The following `multiplier` letters are defined:
    #
    # * `m` (milli): multiply by 0.001
    # * `u` (micro): multiply by 0.000001
    # * `n` (nano): multiply by 0.000000001
    # * `p` (pico): multiply by 0.000000000001
    units = {
        'p': 10**12,
        'n': 10**9,
        'u': 10**6,
        'm': 10**3,
    }
    unit = str(amount)[-1]
    # BOLT #11:
    # A reader SHOULD fail if `amount` contains a non-digit, or is followed by
    # anything except a `multiplier` in the table above.
    if not re.fullmatch("\\d+[pnum]?", str(amount)):
        raise ValueError("Invalid amount '{}'".format(amount))

    if unit in units.keys():
        return Decimal(amount[:-1]) / units[unit]
    else:
        return Decimal(amount)


# Try to pull out tagged data: returns tag, tagged data and remainder.
def pull_tagged(stream):
    tag = stream.read(5).uint
    length = stream.read(5).uint * 32 + stream.read(5).uint
    return (CHARSET[tag], stream.read(length * 5), stream)


# Discard trailing bits, convert to bytes.
def trim_to_bytes(barr):
    # Adds a byte if necessary.
    b = barr.tobytes()
    if barr.len % 8 != 0:
        return b[:-1]
    return b


def lndecode(invoice: str, *, verbose=False, expected_hrp=None) -> LnAddr:
    if expected_hrp is None:
        expected_hrp = SEGWIT_HRP
    decoded_bech32 = bech32_decode(invoice, ignore_long_length=True)
    hrp = decoded_bech32.hrp
    data = decoded_bech32.data
    if decoded_bech32.encoding is None:
        raise ValueError("Bad bech32 checksum")
    if decoded_bech32.encoding != Encoding.BECH32:
        raise ValueError("Bad bech32 encoding: must be using vanilla BECH32")

    # BOLT #11:
    #
    # A reader MUST fail if it does not understand the `prefix`.
    if not hrp.startswith('ln'):
        raise ValueError("Does not start with ln")

    if not hrp[2:].startswith(expected_hrp):
        raise ValueError("Wrong Lightning invoice HRP " + hrp[2:] + ", should be " + expected_hrp)

    data = u5_to_bitarray(data)

    # Final signature 65 bytes, split it off.
    if len(data) < 65*8:
        raise ValueError("Too short to contain signature")
    sigdecoded = data[-65*8:].tobytes()
    data = bitstring.ConstBitStream(data[:-65*8])

    addr = LnAddr()
    addr.pubkey = None

    m = re.search("[^\\d]+", hrp[2:])
    if m:
        addr.currency = m.group(0)
        amountstr = hrp[2+m.end():]
        # BOLT #11:
        #
        # A reader SHOULD indicate if amount is unspecified, otherwise it MUST
        # multiply `amount` by the `multiplier` value (if any) to derive the
        # amount required for payment.
        if amountstr != '':
            addr.amount = unshorten_amount(amountstr)

    addr.date = data.read(35).uint

    while data.pos != data.len:
        tag, tagdata, data = pull_tagged(data)

        # BOLT #11:
        #
        # A reader MUST skip over unknown fields, an `f` field with unknown
        # `version`, or a `p`, `h`, or `n` field which does not have
        # `data_length` 52, 52, or 53 respectively.
        data_length = len(tagdata) / 5

        if tag == 'r':
            # BOLT #11:
            #
            # * `r` (3): `data_length` variable.  One or more entries
            # containing extra routing information for a private route;
            # there may be more than one `r` field, too.
            #    * `pubkey` (264 bits)
            #    * `short_channel_id` (64 bits)
            #    * `feebase` (32 bits, big-endian)
            #    * `feerate` (32 bits, big-endian)
            #    * `cltv_expiry_delta` (16 bits, big-endian)
            route = []
            s = bitstring.ConstBitStream(tagdata)
            while s.pos + 264 + 64 + 32 + 32 + 16 < s.len:
                route.append((s.read(264).tobytes(),
                              s.read(64).tobytes(),
                              s.read(32).uintbe,
                              s.read(32).uintbe,
                              s.read(16).uintbe))
            addr.tags.append(('r',route))
        elif tag == 't':
            s = bitstring.ConstBitStream(tagdata)
            e = (s.read(264).tobytes(),
                 s.read(32).uintbe,
                 s.read(32).uintbe,
                 s.read(16).uintbe)
            addr.tags.append(('t', e))
        elif tag == 'f':
            fallback = None
            if fallback:
                addr.tags.append(('f', fallback))
            else:
                # Incorrect version.
                addr.unknown_tags.append((tag, tagdata))
                continue

        elif tag == 'd':
            addr.tags.append(('d', trim_to_bytes(tagdata).decode('utf-8')))

        elif tag == 'h':
            if data_length != 52:
                addr.unknown_tags.append((tag, tagdata))
                continue
            addr.tags.append(('h', trim_to_bytes(tagdata)))

        elif tag == 'x':
            addr.tags.append(('x', tagdata.uint))

        elif tag == 'p':
            if data_length != 52:
                addr.unknown_tags.append((tag, tagdata))
                continue
            addr.paymenthash = trim_to_bytes(tagdata)

        elif tag == 's':
            if data_length != 52:
                addr.unknown_tags.append((tag, tagdata))
                continue
            addr.payment_secret = trim_to_bytes(tagdata)

        elif tag == 'n':
            if data_length != 53:
                addr.unknown_tags.append((tag, tagdata))
                continue
            pubkeybytes = trim_to_bytes(tagdata)
            addr.pubkey = pubkeybytes

        elif tag == 'c':
            addr._min_final_cltv_expiry = tagdata.uint

        elif tag == '9':
            features = tagdata.uint
            addr.tags.append(('9', features))

        else:
            addr.unknown_tags.append((tag, tagdata))

    if verbose:
        print('hex of signature data (32 byte r, 32 byte s): {}'
              .format(hexlify(sigdecoded[0:64])))
        print('recovery flag: {}'.format(sigdecoded[64]))
        print('hex of data for signing: {}'
              .format(hexlify(hrp.encode("ascii") + data.tobytes())))
        print('SHA256 of above: {}'.format(sha256(hrp.encode("ascii") + data.tobytes()).hexdigest()))

    # BOLT #11:
    #
    # A reader MUST check that the `signature` is valid (see the `n` tagged
    # field specified below).
    addr.signature = sigdecoded[:65]
    hrp_hash = sha256(hrp.encode("ascii") + data.tobytes()).digest()
    # Not done

    return addr

"""
Module for opening lightning channels in a batched way.
"""
from math import ceil
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from lndmanage.lib.types import UTXO, AddressType
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# transaction component sizes
# parameters via github.com/virtu/libtxsize
# ./libtxsize-cli.py -i P2SH-P2WPKH,P2WPKH -o P2WSH-2-of-2-MULTISIG,P2WPKH

# version, locktime, nins, nouts
TRANSACTION_OVERHEAD_VBYTES = 8 + 1 + 1
# inputs
P2WPKH_INPUT_VBYTES = 41
P2SH_P2WPKH_INPUT_VBYTES = 64
# outputs
P2WSH_OUTPUT_VBYTES = 43
P2WPKH_OUTPUT_VBYTES = 31
# witness
P2SH_P2WPKH_INPUT_WITNESS_WEIGHT = 109
P2WPKH_INPUT_WITNESS_WEIGHT = 109
MARKER_FLAG_WEIGHT = 2
WITNESS_NUM_INPUT_WEIGHT = 1
WITNESS_SCALE = 4

ANCHOR_RESERVE = 10 * 10000
MAX_ANCHOR_RESERVE = 5 * ANCHOR_RESERVE
MIN_CHANNEL_SIZE = 500000
WUMBO_LIMIT = 16777215

def calculate_fees(sat_per_vbyte: int, num_p2wkh_inputs: int, num_np2wkh_inputs,
                   num_channels: int, has_change=False) -> int:
    """Calculates the size (in vbytes) of a transaction and determines the fee."""
    # see also https://github.com/btcsuite/btcwallet/tree/master/wallet/txsizes/size.go
    # for lnd fee calculation
    size_vbytes = 0
    size_vbytes += TRANSACTION_OVERHEAD_VBYTES
    size_vbytes += P2WPKH_INPUT_VBYTES * num_p2wkh_inputs
    size_vbytes += P2SH_P2WPKH_INPUT_VBYTES * num_np2wkh_inputs
    size_vbytes += P2WSH_OUTPUT_VBYTES * num_channels

    # due to a bug in lnd fee estimation, we always add a change output here
    size_vbytes += P2WPKH_OUTPUT_VBYTES

    if has_change:
        size_vbytes += P2WPKH_OUTPUT_VBYTES

    # add witness data
    witness_weight = 0
    witness_weight += MARKER_FLAG_WEIGHT
    witness_weight += WITNESS_NUM_INPUT_WEIGHT
    witness_weight += P2WPKH_INPUT_WITNESS_WEIGHT * num_p2wkh_inputs
    witness_weight += P2SH_P2WPKH_INPUT_WITNESS_WEIGHT * num_np2wkh_inputs

    # for the total vbytes, discount witness data
    size_vbytes = size_vbytes + (witness_weight + 3) / WITNESS_SCALE

    logger.debug(
        f"    Transaction size calculation for "
        f"{num_p2wkh_inputs} (p2wkh) + {num_np2wkh_inputs} (np2wkh) inputs, {num_channels}"
        f"channels, change {has_change}: {int(size_vbytes)} vbytes"
    )
    # take an overestimation, let LND reduce fees (as LND's fee estimation is buggy)
    return int(size_vbytes * sat_per_vbyte)


def count_input_types(utxos: List[UTXO]) -> Tuple[int, int]:
    """Count the number of p2wkh and np2wkh inputs in the list of UTXOs."""
    num_p2wkh = 0
    num_npw2kh = 0
    for utxo in utxos:
        if utxo.transaction_type == AddressType.WITNESS_PUBKEY_HASH:
            num_p2wkh += 1
        elif utxo.transaction_type == AddressType.NESTED_PUBKEY_HASH:
            num_npw2kh += 1
    return num_p2wkh, num_npw2kh


def provide_coins(utxos: List[UTXO], total_amount_requested: Optional[int],
                  spend_all_utxos: bool, sat_per_vbyte: int, num_channels: int,
                  anchor_reserve: int) -> Tuple[List[UTXO], int, int, int]:
    """Selects coins from a list of UTXOs to spend a total amount.

    A total amount of None indicates that we want to spend all uxtos.

    If spend_all_utxos is true, all utxos will be included as the inputs, and
    change is accordingly created.
    The coin selection handles the reservation of anchor funds.

    :returns
    included UTXOS,
    total budget spendable in sat,
    change amount in sat,
    fee amount in sat
    """
    available_utxos = sorted(utxos, reverse=True)  # decreasing order

    if not total_amount_requested:  # try to spend the full UTXO set
        create_anchor_output = bool(anchor_reserve)
        # Here we try to spend all funds. If we should reserve some funds for
        # anchor outputs, we try to take some already existent small UTXOs. If
        # that's not possible, we need to create a change output.
        anchor_utxos = []
        if create_anchor_output:
            # Search for viable anchor UTXOs beginning from the smallest UTXO.
            for utxo in reversed(available_utxos):
                anchor_utxos.append(utxo)
                if anchor_reserve <= sum(utxo.amount_sat for utxo in anchor_utxos) <= MAX_ANCHOR_RESERVE:
                    logger.info("    Reserving UTXOs for anchors:")
                    for anchor_utxo in anchor_utxos:
                        logger.info(f"    {str(anchor_utxo)}")
                        available_utxos.remove(anchor_utxo)
                    create_anchor_output = False
                    break
        num_p2wkh, num_np2wkh = count_input_types(available_utxos)
        fee = calculate_fees(
            sat_per_vbyte,
            num_p2wkh_inputs=num_p2wkh,
            num_np2wkh_inputs=num_np2wkh,
            num_channels=num_channels,
            has_change=create_anchor_output
        )
        anchor_change = anchor_reserve if create_anchor_output else 0
        budget = sum(utxo.amount_sat for utxo in available_utxos) \
            - anchor_change - fee
        if budget < 0:
            raise ValueError(f"Not enough funds for channel opening.")
        change = anchor_change
        return available_utxos, budget, change, fee

    else:  # We try to spend a smaller amount than the given UTXO set.
        # We need to include change either because funds are left over
        # or we need to keep the anchor reserve.
        create_change = True
        if spend_all_utxos:  # user wants to batch all inputs together
            num_p2wkh, num_np2wkh = count_input_types(utxos)
            fee = calculate_fees(
                sat_per_vbyte,
                num_p2wkh_inputs=num_p2wkh,
                num_np2wkh_inputs=num_np2wkh,
                num_channels=num_channels,
                has_change=create_change
            )
            utxo_sum = sum(utxo.amount_sat for utxo in utxos)
            budget = min(total_amount_requested, utxo_sum - fee)
            if budget < 0:
                raise ValueError(f"Not enough funds for channel opening.")
            change = utxo_sum - budget - fee
            return utxos, budget, change, fee

        else:  # we need to do coin selection
            selected_utxos = []
            utxo_sum = 0
            for utxo in available_utxos:
                utxo_sum += utxo.amount_sat
                selected_utxos.append(utxo)
                num_p2wkh, num_np2wkh = count_input_types(selected_utxos)
                fee = calculate_fees(
                    sat_per_vbyte,
                    num_p2wkh_inputs=num_p2wkh,
                    num_np2wkh_inputs=num_np2wkh,
                    num_channels=num_channels,
                    has_change=True
                )
                if total_amount_requested + fee + anchor_reserve <= utxo_sum:
                    change = utxo_sum - total_amount_requested - fee
                    return selected_utxos, total_amount_requested, change, fee
    raise ValueError("Don't have enough funds.")


class ChannelOpener(object):
    """Opens multiple channels at once."""

    def __init__(self, node: 'LndNode'):
        self.node = node

    def _parse_pubkeys(self, pubkeys: str) -> List[str]:
        pubkeys = pubkeys.split(',')
        pubkeys = [c.strip() for c in pubkeys]
        return pubkeys

    def _pubkeys_to_bytes(self, pubkeys: List[str]) -> List[bytes]:
        return [bytes.fromhex(pubkey) for pubkey in pubkeys]

    @staticmethod
    def _parse_amounts(amounts: str) -> Optional[List[int]]:
        if amounts:
            amount_ints = amounts.split(',')
            amount_ints = [int(a) for a in amount_ints]
            return amount_ints
        else:
            return None

    @staticmethod
    def _parse_utxo_outpoints(utxos_str: str) -> Optional[List[UTXO]]:
        if utxos_str:
            utxo_strings = utxos_str.split(',')
            utxos = []
            for u in utxo_strings:
                try:
                    txid, output_index = u.split(':')
                except ValueError:
                    raise ValueError("utxo format is not of txid:index")
                utxos.append(
                    UTXO(txid=str(txid), output_index=int(output_index))
                )
            return utxos
        else:
            return None

    def open_channels(self, *, pubkeys: str, amounts: str = None,
                      utxos: Optional[str] = None, sat_per_vbyte=1,
                      total_amount: Optional[int] = None, reckless=False,
                      private=False):
        """
        Performs input checks on parameters and performs user interaction for
        batch channel opening.

        pubkeys: comma separated nodeid1,nodeid2,...
        amounts: comma separated amount1,amount2,...
        utxos: txid:output_idx,txid:output_idx,...
        sat_per_vbyte: onchain fee rate
        total_amount: if amounts are not specified, a total amount is
            distributed to all peers

        Steps:
        1. connect to nodes
        2. report about errors and demand actions (TODO)
        3. check provided utxos (if any)
        4. calculate budget without fees and anchor reserve
        5. open channels

        """
        # Possible improvements:
        # add close_addresses for upfront shutdown script
        pubkeys = self._parse_pubkeys(pubkeys)
        amounts = self._parse_amounts(amounts)

        if amounts and total_amount:
            raise ValueError("Specify either amounts or total amount.")

        if amounts and len(amounts) != len(pubkeys):
            raise ValueError("Number of amounts is not equal to number of"
                             "node pubkeys.")
        # 1. connect to nodes
        try:
            pubkeys_succeeded = self.node._connect_nodes(pubkeys)
        except ConnectionRefusedError:
            logger.info(">>> Could not connect to all nodes. Try to connect "
                        "manually via 'lncli connect', then rerun.")
            return

        assert len(pubkeys) == len(pubkeys_succeeded)
        pubkeys = self._pubkeys_to_bytes(pubkeys_succeeded)
        num_channels = len(pubkeys)

        # 2. report about errors
        # TODO: report about connection errors and how to proceed
        # maybe reduce number of peers, or suggest new list of peers that the
        # user can copy-paste

        # 3. check utxos
        wallet_utxos = self.node.get_utxos()
        wallet_balance = sum(utxo.amount_sat for utxo in wallet_utxos)
        user_provided_utxos = self._parse_utxo_outpoints(utxos)

        available_utxos = []
        if user_provided_utxos:
            for utxo in user_provided_utxos:
                if utxo in wallet_utxos:
                    # need to do index lookups here to also get additional info on the utxos
                    available_utxos.append(wallet_utxos[wallet_utxos.index(utxo)])
                else:
                    raise ValueError(f"UTXO {utxo} is not controlled by the wallet")
        else:
            available_utxos = wallet_utxos
        available_balance = sum(utxo.amount_sat for utxo in available_utxos)

        if not available_utxos:
            raise ValueError("no UTXOs available'")
        logger.info(">>> Available UTXOs:")
        for utxo in available_utxos:
            logger.debug(f"    {utxo.txid}:{utxo.output_index} {utxo.amount_sat} sat")

        if available_balance > wallet_balance - ANCHOR_RESERVE:
            # the user included maybe too many UTXOs that may spend beyond the anchor reserve
            logger.debug("    Need to potentially consider anchor outputs.")
            anchor_reserve = ANCHOR_RESERVE
        else:
            anchor_reserve = 0

        if (sum(utxo.amount_sat for utxo in available_utxos) - anchor_reserve) \
                / num_channels < MIN_CHANNEL_SIZE:
            raise ValueError(f"The total available funds are not enough to "
                             f"fund {num_channels} channels with minimal size of "
                             f"{MIN_CHANNEL_SIZE} sat. (Anchor reserve: "
                             f"{anchor_reserve} sat.)")

        # 4. calculate budget
        # Amounts and total_amount are mutually exclusive. Total amount of None
        # indicates a full spend.
        if amounts:
            total_amount = sum(amounts)
            if total_amount < 100:
                total_amount = None
        elif total_amount:
            amounts = [int(total_amount / num_channels) for _ in pubkeys]
        else:
            total_amount = None

        # If the total amount doesn't resepect the anchor reserve, make it a full spend.
        if total_amount and total_amount > available_balance - anchor_reserve:
            total_amount = None

        utxos, budget, change, fee = provide_coins(
            utxos=available_utxos,
            spend_all_utxos=bool(utxos),  # user provided some utxos
            total_amount_requested=total_amount,
            sat_per_vbyte=sat_per_vbyte,
            num_channels=num_channels,
            anchor_reserve=anchor_reserve,
        )
        logger.info(">>> Used UTXOs:")
        for utxo in utxos:
            logger.info(f"    {utxo.txid}:{utxo.output_index} {utxo.amount_sat} sat")
        logger.info(f">>> Channels will be {'private' if private else 'public'}.")

        def rescale(amounts: List[int], rescaled_total_amount: int) -> List[int]:
            """Rescales list of amounts to amounts with sum of
            rescaled_total_amount, fixing also rounding errors."""
            tot_amt = sum(amounts)
            amounts = [rescaled_total_amount * a // tot_amt for a in amounts]
            # handle rounding errors
            diff = rescaled_total_amount - sum(amounts)
            amounts[-1] += diff
            return amounts

        if not total_amount:
            if not amounts:
                # distribute the total budget equally over all channels
                amounts = [int(budget / num_channels) for _ in pubkeys]
            else:
                amounts = rescale(amounts, budget)

        logger.info(f"    Channel capacities: {amounts} sat ({sum(amounts)} sat total).")
        logger.info(f"    Fees: {fee} sat ({sat_per_vbyte} sat/vbyte).")
        logger.info(f"    Change: {change} sat.")

        # TODO: check connected node's features and allow wumbo channels
        # if own node supports it
        for amount in amounts:
            if amount > WUMBO_LIMIT:
                raise ValueError("Wumbo channels (capacity bigger than 16777215 sat) not yet supported.")

        # 5. open channels
        try:
            self.node.open_channels(
                pubkeys=pubkeys,
                amounts_sat=amounts,
                change_sat=change,
                utxos=utxos,
                reckless=reckless,
                private=private,
                sat_per_vbyte=sat_per_vbyte,
            )
        except Exception as e:
            logger.exception(e)
            pass

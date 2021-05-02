"""
Module for opening lightning channels in a batched way to save onchain fees.
"""
import logging
import pprint
from typing import TYPE_CHECKING, List, Optional, Tuple

from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Fee definitions
TRANSACTION_OVERHEAD_BYTES = 12
P2WPKH_INPUT_BYTES = 41 + 107
P2WSH_OUTPUT_BYTES = 43
P2WPKH_OUTPUT_BYTES = 31
BUFFER_BYTES = 100
MIN_CHANGE_AND_FEES = 100000


class UTXO(object):
    def __init__(self, txid: str, outpoint: int):
        self.txid = txid
        self.outpoint = outpoint


def calculate_fees(sat_per_byte: int, number_inputs: int, number_channels: int, change=False) -> int:
    size_bytes = 0
    size_bytes += TRANSACTION_OVERHEAD_BYTES
    size_bytes += P2WPKH_INPUT_BYTES * number_inputs
    size_bytes += P2WSH_OUTPUT_BYTES * number_channels
    if change:
        size_bytes += P2WPKH_OUTPUT_BYTES  # for change output
    logger.info(f"    Transaction size calculation for {number_inputs} inputs, {number_channels} channels, change {change}: {size_bytes} bytes")
    return int(size_bytes * sat_per_byte)


class ChannelOpener(object):

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
    def _parse_utxo_outpoints(utxos: str) -> Optional[List[Tuple[str, int]]]:
        if utxos:
            utxo_strings = utxos.split(',')
            outpoints = []
            for u in utxo_strings:
                try:
                    txid, output_index = u.split(':')
                except ValueError:
                    raise ValueError("utxo format is not of txid:index")
                outpoints.append((txid, int(output_index)))
            return outpoints
        else:
            return None

    def open_channels(self, *, pubkeys: str, amounts: Optional[str],
                      utxos: Optional[str] = None, sat_per_byte=1,
                      total_amount: Optional[int] = None, reckless=False,
                      private=False):
        """
        Performs input checks on parameters and performs user interaction for
        batch channel opening.

        pubkeys: comma separated nodeid1,nodeid2,...
        amounts: comma separated amount1,amount2,...
        utxos: txid:output_idx,txid:output_idx,...
        sat_per_byte: onchain fee rate
        total_amount: if amounts are not specified, a total amount is distributed
            to all peers

        Steps:
        1. connect to nodes
        2. report about errors and demand actions (TBD)
        3. check provided utxos (if any)
        4. check amounts and calculate budget (if any)
        5. open channels

        """
        # TODO: add close_addresses for upfront shutdown script
        pubkeys = self._parse_pubkeys(pubkeys)
        amounts = self._parse_amounts(amounts)

        if amounts and total_amount:
            raise ValueError("Specify either amounts or total amount.")

        if amounts and len(amounts) != len(pubkeys):
            raise ValueError("Number of amounts is not equal to number of"
                             "node connection strings.")
        # 1. connect to nodes
        try:
            pubkeys_succeeded = self.node._connect_nodes(pubkeys)
        except Exception as e:
            logger.info(e)
            logger.info(">>> Could not connect to all nodes. Try to connect manually via 'lncli connect'.")
            return

        # TODO: handle the case when we couldn't connect to all nodes
        # TODO: account for multiple channels with same node
        assert len(pubkeys) == len(pubkeys_succeeded)
        pubkeys = self._pubkeys_to_bytes(pubkeys_succeeded)
        number_channels = len(pubkeys)

        # 2. report about errors
        # TODO: report about connection errors and how to proceed

        # 3. check utxos
        wallet_utxos = self.node.get_utxos()
        utxos = self._parse_utxo_outpoints(utxos)
        used_utxos = {}
        if utxos:
            for utxo_outpoint in utxos:
                if utxo_outpoint not in wallet_utxos:
                    raise ValueError(f"utxo {utxo_outpoint} is not controlled by the wallet")
                used_utxos[utxo_outpoint] = wallet_utxos[utxo_outpoint]
        else:
            used_utxos = wallet_utxos
        # TODO: warn user / reserve one outpoint for anchor commitments
        if not used_utxos:
            raise ValueError("no utxos available")
        logger.info(f">>> Using UTXOs:\n    {pprint.pformat(used_utxos, indent=4)}")

        # 4. calculate budget
        budget = 0
        number_utxos = 0
        for amount in used_utxos.values():
            budget += amount
            number_utxos += 1
        logger.info(f">>> Planned channel opening: total budget: {budget} sat, ({number_utxos} input(s))")
        logger.info(f">>> Channels will be {'private' if private else 'public'}.")

        if not amounts:
            if total_amount:
                amounts = [int(total_amount / number_channels) for _ in pubkeys]
            else:
                amounts = [int(budget / number_channels) for _ in pubkeys]

        amount_requested = sum(amounts)
        logger.info(f">>> Total requested amount: {amount_requested} sat.")
        # amounts are now set

        # handle the case when we have change
        change_amount = 0
        if (amount_requested >= 100) and (amount_requested < budget - MIN_CHANGE_AND_FEES):
            fees = calculate_fees(sat_per_byte, number_utxos, number_channels, change=True)
            change_amount = budget - amount_requested - fees
            amount_channels = budget - change_amount - fees
        else:
            fees = calculate_fees(sat_per_byte, number_utxos, number_channels, change=False)
            amount_channels = budget - fees

        # normalize amounts
        amounts = [int(amount_channels * a / amount_requested) for a in amounts]

        logger.info(f"    Channel capacities: {amounts} sat ({sum(amounts)} sat total).")
        logger.info(f"    Transaction fees: {fees} sat ({sat_per_byte} sat/byte).")
        logger.info(f"    Change amount: {change_amount} sat.")

        # 5. open channels
        try:
            self.node._open_channels(
                pubkeys=pubkeys,
                amounts=amounts,
                change_amount=change_amount,
                utxos=used_utxos,
                sat_per_byte=sat_per_byte,
                reckless=reckless,
                private=private,
            )
        except Exception as e:
            logger.info(e)
            pass

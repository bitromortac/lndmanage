"""
Module for opening lightning channels in a batched way.
"""
from math import ceil
import logging
from typing import TYPE_CHECKING, List, Optional

from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

ANCHOR_RESERVE = 10 * 10000
WUMBO_LIMIT = 16777215


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
            amounts_split = []
            for a in amount_ints:
                a = int(a)
                if a < 0:
                    raise ValueError("amount negative")
                amounts_split.append(a)
            return amounts_split
        return None

    def open_channels(self, *, pubkeys: str, amounts: str = None,
                      sat_per_vbyte=1, total_amount: Optional[int] = None,
                      private=False, test=False):
        """
        Performs input checks on parameters and performs user interaction for
        batch channel opening.

        pubkeys: comma separated nodeid1,nodeid2,...
        amounts: comma separated amount1,amount2,...
        sat_per_vbyte: onchain fee rate
        total_amount: if amounts are not specified, a total amount is
            distributed to all peers

        Steps:
        1. connect to nodes
        2. report about errors and demand actions (TODO)
        3. calculate amounts
        4. open channels

        """
        # Possible improvements:
        # add close_addresses for upfront shutdown script
        pubkeys = self._parse_pubkeys(pubkeys)
        amounts = self._parse_amounts(amounts)

        if not amounts and not total_amount:
            raise ValueError("Please specify either the total amount or amounts.")

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
        available_utxos = self.node.get_utxos()
        wallet_balance = sum(utxo.amount_sat for utxo in available_utxos)

        if not available_utxos:
            raise ValueError("no UTXOs available'")

        # 4. calculate budget
        # Amounts and total_amount are mutually exclusive.
        if amounts:
            total_amount = sum(amounts)
        elif total_amount:
            amounts = [int(total_amount / num_channels) for _ in pubkeys]

        if total_amount > wallet_balance - ANCHOR_RESERVE:
            raise ValueError("Total amount exceeds wallet balance (anchor reserve included)")

        logger.info(f"    Channel capacities: {amounts} sat ({sum(amounts)} sat total).")

        # TODO: check connected node's features and allow wumbo channels
        #  if own node supports it
        for amount in amounts:
            if amount > WUMBO_LIMIT:
                raise ValueError("Wumbo channels (capacity bigger than 16777215 sat) not yet supported.")

        # 5. open channels
        try:
            self.node.open_channels(
                pubkeys=pubkeys,
                amounts_sat=amounts,
                private=private,
                sat_per_vbyte=sat_per_vbyte,
                test=test,
            )
        except Exception as e:
            logger.exception(e)
            pass

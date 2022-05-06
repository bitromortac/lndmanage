from enum import Enum
from dataclasses import dataclass, field
from typing import Tuple


class AddressType(Enum):
    WITNESS_PUBKEY_HASH = 0
    NESTED_PUBKEY_HASH = 1


@dataclass(order=True)
class UTXO:
    sort_index: int = field(init=False, repr=False)
    txid: str
    output_index: int
    amount_sat: int = None
    transaction_type: AddressType = None

    def __post_init__(self):
        self.sort_index = self.amount_sat

    def __hash__(self):
        return hash(self.txid) + hash(self.output_index)

    def __eq__(self, other: "UTXO"):
        if self.txid == other.txid and self.output_index == other.output_index:
            return True
        else:
            return False

    def __str__(self):
        return f"{self.txid}:{self.output_index} {self.amount_sat} sat"


@dataclass(order=True)
class NodeProperties:
    age: int
    local_fee_rates: list
    local_base_fees: list
    local_balances: list
    number_active_channels: int
    number_channels: int
    number_private_channels: int
    public_capacities: list
    private_capacites: list
    remote_fee_rates: list
    remote_base_fees: list
    remote_balances: list
    sent_received_per_week: int


class NodePair(tuple):
    """Represents a node pair mapped to a fixed order."""

    def __new__(cls, keys: Tuple[str, str]):
        if keys[0].casefold() < keys[1].casefold():
            seq = (keys[0], keys[1])
        else:
            seq = (keys[1], keys[0])

        return super().__new__(cls, seq)

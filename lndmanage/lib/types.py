from enum import Enum
from dataclasses import dataclass, field


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

    def __eq__(self, other: 'UTXO'):
        if self.txid == other.txid and self.output_index == other.output_index:
            return True
        else:
            return False

    def __str__(self):
        return f"{self.txid}:{self.output_index} {self.amount_sat} sat"
from typing import NamedTuple
from datetime import datetime
from lndmanage.lib.lninvoice import lndecode

class Payment(NamedTuple):
    payment_hash: str
    amount_msat: int
    creation_time: datetime
    memo: str

    @classmethod
    def from_lnd_proto(cls, proto):
        memo = ''
        if proto.payment_request:
            invoice = lndecode(proto.payment_request)
            tags = dict(invoice.tags)
            memo = tags.get('d', '')
        return Payment(
            payment_hash=str(proto.payment_hash),
            amount_msat=int(proto.value_msat),
            creation_time=datetime.utcfromtimestamp(proto.creation_time_ns / 1E9),
            memo=str(memo),
        )


class Invoice(NamedTuple):
    payment_hash: str
    amount_msat: int
    settle_date: datetime
    memo: str

    @classmethod
    def from_lnd_proto(cls, proto):
        return Invoice(
            payment_hash=str(proto.r_hash.hex()),
            amount_msat=int(proto.value_msat),
            settle_date=datetime.utcfromtimestamp(proto.settle_date),
            memo=str(proto.memo),
        )


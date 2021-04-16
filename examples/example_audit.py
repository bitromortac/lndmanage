import csv
from datetime import datetime
from typing import TYPE_CHECKING, List, Union
from collections import namedtuple

from lndmanage.lib.node import LndNode
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.types import Payment, Invoice

import logging.config
logging.config.dictConfig(settings.logger_config)

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    node = LndNode(config_file='/home/user/.lndmanage/config.ini')
    payments = node.get_payments(max_payments=10000)
    invoices = node.get_invoices(max_invoices=10000)
    def data_to_csv(filename: str, data: Union[List['Payment'], List['Invoice']]):
        with open(filename, 'w') as f:
            csv_writer = csv.writer(f)
            if data:
                csv_writer.writerow([f for f in data[0]._field_types.keys()])
                for d in data:
                    csv_writer.writerow([getattr(d, f) for f in d._field_types.keys()])
    data_to_csv('payments.csv', payments)
    data_to_csv('invoices.csv', invoices)

    forwardings = node.get_forwarding_events(offset_days=800)

    with open('forwardings.csv', 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(['timestamp', 'amt_in_msat', 'amt_out_msat'])
        for f in forwardings:
            csv_writer.writerow([datetime.utcfromtimestamp(f['timestamp']), f['amt_in_msat'], f['amt_out_msat']])


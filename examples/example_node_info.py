import _settings
from lib.listchannels import print_channels_rebalance
from lib.node import LndNode

import logging.config
logging.config.dictConfig(_settings.logger_config)

if __name__ == '__main__':
    node = LndNode()
    node.print_status()
    print_channels_rebalance(node, unbalancedness_greater_than=_settings.UNBALANCED_CHANNEL)

import _settings
from lib.node_info import print_node_status, print_unbalanced_channels
from lib.node import LndNode

import logging.config
logging.config.dictConfig(_settings.logger_config)

if __name__ == '__main__':
    node = LndNode()
    print_node_status(node)
    print_unbalanced_channels(node, unbalancedness_greater_than=_settings.UNBALANCED_CHANNEL)

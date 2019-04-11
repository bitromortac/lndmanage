import _settings
from lib.node import LndNode

import logging.config
logging.config.dictConfig(_settings.logger_config)

node = LndNode()
print(f"Number of nodes: {node.network.graph.order()}")
print(f"Number of channels: {len(node.network.edges.keys())}")

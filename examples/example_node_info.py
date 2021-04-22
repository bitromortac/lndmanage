from lndmanage.lib.listchannels import ListChannels
from lndmanage.lib.node import LndNode
from lndmanage import settings

import logging.config
logging.config.dictConfig(settings.lndm_logger_config)

if __name__ == '__main__':
    node = LndNode()
    listchannels = ListChannels(node)
    node.print_status()
    listchannels.print_channels_unbalanced(
        unbalancedness=settings.UNBALANCED_CHANNEL, sort_string='alias')

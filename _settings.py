import os
import configparser

config = configparser.ConfigParser()
dirname = os.path.dirname(__file__)
filename = os.path.join(dirname, 'config.ini')

config.read(filename)

# -------- graph settings --------
# accepted age of the network graph
CACHING_RETENTION_MINUTES = 30

# -------- pathfinding --------
# default penalty for non-active channels / too small channels / unbalanced channels
PENALTY = 1E9
# if a penalty should be applied for long paths
PREFER_SHORT_PATHS = True
# penalty per hop in msats, used together with PREFER_SHORT_PATHS
LONG_PATH_PENALTY_MSAT = 2000
# exclude channels, which have less than amt * MIN_REL_CHANNEL_CAPACITY
# this can be used to increase success rates
MIN_REL_CHANNEL_CAPACITY = 0.75

# -------- network analysis --------
# a user typically has a low number of channels, this number
NUMBER_CHANNELS_DEFINING_USER_NODE = 3

# -------- rebalancing --------
# in terms of unbalancedness
UNBALANCED_CHANNEL = 0.2
# rebalancing will be done with CHUNK_SIZE of the minimal capacity of the to be balanced channels
CHUNK_SIZE = 1.0

# -------- logging --------
# debug level can be INFO or DEBUG
DEBUG_LEVEL = config['logging']['loglevel']

logger_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'file': {
            'format': '[%(asctime)s %(levelname)s] %(message)s',
            #'format': '[%(asctime)s %(levelname)s %(name)s] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
        'standard': {
            'format': '%(message)s',
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',  # Default is stderr
        },
        'file': {
            'level': 'DEBUG',
            'formatter': 'file',
            'class': 'logging.FileHandler',
            'filename': 'lndmanage.log',
        },
    },
    'loggers': {
        '': {  # root logger
            'handlers': ['default', 'file'],
            'level': 'DEBUG',
            'propagate': True
        },
    }
}

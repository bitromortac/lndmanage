import os
import configparser
from lndmanage.lib.configure import check_or_create_configuration
from pathlib import Path

# ======== LNDMANAGE =========
# -------- graph settings --------
# accepted age of the network graph
CACHING_RETENTION_MINUTES = 30

# -------- pathfinding --------
# default penalty for non-active channels / too small channels / unbalanced channels
PENALTY = 1E9
# if a penalty should be applied for long paths
PREFER_SHORT_PATHS = True
# penalty per hop in msat, used together with PREFER_SHORT_PATHS
LONG_PATH_PENALTY_MSAT = 2000
# exclude channels, which have less than amt * MIN_REL_CHANNEL_CAPACITY
# this can be used to increase success rates
MIN_REL_CHANNEL_CAPACITY = 0.75

# -------- network analysis --------
NUMBER_CHANNELS_DEFINING_USER_NODE = 3
NUMBER_CHANNELS_DEFINING_ROUTING_NODE = 10
NUMBER_CHANNELS_DEFINING_HUB = 200

# -------- rebalancing --------
# in terms of unbalancedness
UNBALANCED_CHANNEL = 0.2
# rebalancing will be done with CHUNK_SIZE of the minimal capacity
# of the to be balanced channels
CHUNK_SIZE = 1.0
REBALANCING_TRIALS = 30

# ======== LNDMANAGED =========
# -------- channel acceptor --------
CHACC_MIN_CHANNEL_SIZE_PRIVATE = 0
CHACC_MAX_CHANNEL_SIZE_PRIVATE = 16777215
CHACC_MIN_CHANNEL_SIZE_PUBLIC = 0
CHACC_MAX_CHANNEL_SIZE_PUBLIC = 16777215


lndm_logger_config = None
lndmd_logger_config = None
home_dir = None


def set_lndmanage_home_dir(directory=None):
    """
    Sets the correct path to the lndmanage home folder.

    :param directory: home folder, overwrites default
    :type directory: str
    """
    global home_dir, lndm_logger_config, lndmd_logger_config

    if directory:
        home_dir = directory
    else:
        # determine home folder, prioritized by environment
        # variable LNDMANAGE_HOME
        environ_home = os.environ.get('LNDMANAGE_HOME')

        if environ_home:
            if not os.path.isabs(environ_home):
                raise ValueError(
                    f'Environment variable LNDMANAGE_HOME must be '
                    f'an absolute path. Current: "{environ_home}"')
            home_dir = environ_home
        else:
            user_home_dir = str(Path.home())
            home_dir = os.path.join(user_home_dir, '.lndmanage')

        # if lndmanage is ran for the first time,
        # we need to create the configuration
        check_or_create_configuration(home_dir)

    # logging for lndmanage
    lndm_logger_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'file': {
                'format': '[%(asctime)s %(levelname)s %(name)s] %(message)s',
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
                'filename': os.path.join(home_dir, 'lndmanage.log'),
                'encoding': 'utf-8',
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

    # logging config for lndmanaged
    lndmd_logger_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'file': {
                'format': '[%(asctime)s %(levelname)s %(name)s] %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            },
            'standard': {
                'format': '[%(asctime)s %(levelname)s %(name)s] %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
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
                'filename': os.path.join(home_dir, 'lndmanaged.log'),
                'encoding': 'utf-8',
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


def read_config(config_path):
    config = configparser.ConfigParser()
    config.read(config_path)
    return config


set_lndmanage_home_dir()

import os
from ast import literal_eval
import configparser
from lndmanage.lib.configure import check_or_create_configuration
from pathlib import Path

def parse_env(key, default, _type=str):
    if _type == str:
        return os.environ.get(key, default)
    return _type(literal_eval(os.environ.get(key, default)))

# -------- graph settings --------
# accepted age of the network graph
CACHING_RETENTION_MINUTES = parse_env('LNDMANAGE_RETENTION_MINUTES', '30', float)

# -------- pathfinding --------
# default penalty for non-active channels / too small channels / unbalanced channels
PENALTY = parse_env('LNDMANAGE_DEFAULT_PENALTY', '1E9', float)
# if a penalty should be applied for long paths
PREFER_SHORT_PATHS = parse_env('LNDMANAGE_PREFER_SHORT_PATHS', 'True', bool)
# penalty per hop in msat, used together with PREFER_SHORT_PATHS
LONG_PATH_PENALTY_MSAT = parse_env('LNDMANAGE_LONG_PATH_PENALTY_MSAT', '2000', int)
# exclude channels, which have less than amt * MIN_REL_CHANNEL_CAPACITY
# this can be used to increase success rates
MIN_REL_CHANNEL_CAPACITY = parse_env('LNDMANAGE_MIN_REL_CAPACITY', '0.75', float)

# -------- network analysis --------
# a user typically has a low number of channels, this number
NUMBER_CHANNELS_DEFINING_USER_NODE = parse_env('LNDMANAGE_USER_NODE_CEIL', '3', int)
NUMBER_CHANNELS_DEFINING_HUB = parse_env('LNDMNANAGE_HUB_NODE_FLOOR', '200', int)

# -------- rebalancing --------
# in terms of unbalancedness
UNBALANCED_CHANNEL = parse_env('LNDMANAGE_UNBALANCED_CHANNEL_CEIL', '0.2', float)


logger_config = None
home_dir = None


def set_lndmanage_home_dir(directory=None):
    """
    Sets the correct path to the lndmanage home folder.

    :param directory: home folder, overwrites default
    :type directory: str
    """
    global home_dir, logger_config

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

    # logger settings
    logfile_path = os.path.join(home_dir, 'lndmanage.log')

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
                'filename': logfile_path,
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

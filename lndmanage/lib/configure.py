import os

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def check_home(home_dir):
    # user runs for first time
    if not os.path.exists(home_dir):
        os.mkdir(home_dir)
        # check if .lnd folder exists
            # if yes, ask user if he wants to use it
                # if yes, set the macaroon/cert paths automatically
        # ask for ip (default: localhost)
        # ask for port (default: 9735)
        # if not macaroon/cert paths already set
            # ask for macaroon path
            # ask for cert path

        # create config file
        # read in config ini template
        # modify variables in template
        # write template to config file
    else:
        config_path = os.path.join(home_dir, 'config.ini')
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Configuration file does not exist. Filename: {config_path}.")

    logger.info('Using %s as lndmanage home folder.', home_dir)


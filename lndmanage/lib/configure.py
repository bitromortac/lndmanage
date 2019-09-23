import os
import configparser

from lndmanage.lib.user import yes_no_question, get_user_input

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

this_file_path = os.path.dirname(os.path.realpath(__file__))


def valid_path(path):
    path = os.path.expanduser(path)
    if os.path.exists(path):
        return path
    else:
        print(f"Error: '{path}' doesn't exist on this host.")
        return False


def valid_host(host):
    try:
        ip, port = host.split(':')
    except ValueError:
        print("Error: Host is not of format '127.0.0.1:10009'")
        return False
    return host


def check_or_create_configuration(home_dir):
    """
    Checks if lndmanage configuration exists, otherwise creates configuration.

    :param home_dir: lndmanage home directory
    :type home_dir: str
    """
    if not os.path.exists(home_dir):  # user runs for the first time
        print(f"Lndmanage is not yet configured it seems.")
        print(f"Will set up a configuration folder at {home_dir}.")
        print("The default path can be overridden by setting the "
              "LNDMANAGE_HOME environment variable.")
        print("Do you run your lnd node on this host [Y/n]?")
        lnd_on_this_host = yes_no_question(default='y')

        if lnd_on_this_host:
            potential_lnd_home = os.path.expanduser('~/.lnd')
            lnd_grpc_host = 'localhost:10009'
            print(f'Using {lnd_grpc_host} as hostname.')
            if os.path.exists(potential_lnd_home):
                print(f'Detected lnd home directory: {potential_lnd_home}')
                lnd_home = potential_lnd_home
            else:
                print('Enter path to the .lnd folder:')
                lnd_home = get_user_input(valid_path)
            admin_macaroon_path = os.path.join(
                lnd_home, 'data/chain/bitcoin/mainnet/admin.macaroon')
            tls_cert_path = os.path.join(
                lnd_home, 'tls.cert')

        else:  # lnd runs on different host
            print('Enter remote host information (format: 127.0.0.1:10009)')
            lnd_grpc_host = get_user_input(valid_host)
            print('Enter admin macaroon location (can be found '
                  'in remote:.lnd/data/chain/bitcoin/mainnet/admin.macaroon)')
            admin_macaroon_path = get_user_input(valid_path)
            print('Enter TLS certificate path (can be found in '
                  'remote:.lnd/tls.cert)')
            tls_cert_path = get_user_input(valid_path)

        # build config file
        config = configparser.ConfigParser()
        os.mkdir(home_dir)
        config_template_path = os.path.join(
            this_file_path, '../templates/config_sample.ini')
        config.read(config_template_path)

        config['network']['lnd_grpc_host'] = str(lnd_grpc_host)
        config['network']['admin_macaroon_file'] = str(admin_macaroon_path)
        config['network']['tls_cert_file'] = str(tls_cert_path)

        config_path = os.path.join(home_dir, 'config.ini')

        with open(config_path, 'w') as configfile:
            config.write(configfile)
        print(f'Config file was written to {config_path}')

    else:
        config_path = os.path.join(home_dir, 'config.ini')
        if not os.path.isfile(config_path):
            raise FileNotFoundError(
                f"Configuration file does not exist. Filename: {config_path}. "
                f"Delete .lndmanage folder and run again.")

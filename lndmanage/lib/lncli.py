"""
Handling lncli interaction.
"""
import os
import subprocess
import json

from pygments import highlight, lexers, formatters
from lndmanage import settings

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Lncli(object):
    def __init__(self, lncli_path, config_file):
        self.lncli_path = lncli_path

        config = settings.read_config(config_file)

        cert_file = os.path.expanduser(config['network']['tls_cert_file'])
        macaroon_file = \
            os.path.expanduser(config['network']['admin_macaroon_file'])
        lnd_host = config['network']['lnd_grpc_host']

        # assemble the command for lncli for execution with flags
        self.lncli_command = [
            self.lncli_path,
            '--rpcserver=' + lnd_host,
            '--macaroonpath=' + macaroon_file,
            '--tlscertpath=' + cert_file
            ]

    def lncli(self, command):
        """
        Invokes the lncli command line interface for lnd.

        :param command: list of command line arguments
        :return:
            int: error code
        """

        cmd = self.lncli_command + command
        logger.debug('executing lncli %s', ' '.join(cmd))
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # check if the output can be decoded from valid json
        try:
            json.loads(proc.stdout)
            # convert json into color coded characters
            colorful_json = highlight(
                proc.stdout,
                lexers.JsonLexer(),
                formatters.TerminalFormatter()
            )
            logger.info(colorful_json)

        # usually errors and help are not json, handle them here
        except ValueError:
            logger.info(proc.stdout.decode('utf-8'))
            logger.info(proc.stderr.decode('utf-8'))

        return proc.returncode

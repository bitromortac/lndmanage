import asyncio
import os

from lndmanage import settings

from lndmanage.lib.managed import LNDManageDaemon

# TODO: configuration, command line flags

def main():
    lndm_config_path = os.path.join(settings.home_dir, 'config.ini')
    lndmd_config_path = os.path.join(settings.home_dir, 'lndmanaged.ini')

    lndmd = LNDManageDaemon(
        lndm_config_path=lndm_config_path,
        lndmd_config_path=lndmd_config_path,
    )
    asyncio.run(lndmd.run_services())


if __name__ == '__main__':
    main()

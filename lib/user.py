import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def yes_no_question():
    """
    Asks the user a yes/no question and translates it into bool.

    :return: bool
    """
    yes = {'yes', 'y', 'ye', ''}
    no = {'no', 'n'}

    choice = input().lower()
    if choice in yes:
        return True
    elif choice in no:
        return False
    else:
        logger.info("Please respond with 'yes' or 'no'")

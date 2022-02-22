import collections
import time

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def convert_dictionary_number_strings_to_ints(data):
    """
    Converts the values of str type to int type where possible.

    :param data: dict
    :return: converted dict
    """
    if isinstance(data, str):
        try:
            data = int(data)
        except ValueError:
            data = str(data)
        return data
    elif isinstance(data, collections.Mapping):
        return dict(map(convert_dictionary_number_strings_to_ints, data.items()))
    elif isinstance(data, collections.Iterable):
        return type(data)(map(convert_dictionary_number_strings_to_ints, data))
    else:
        return data


def profiled(func, *args, **kwargs):
    """Function wrapper for measuring execution time."""
    def wrapper(*args, **kwargs):
        name = func.__qualname__
        start = time.time()
        output = func(*args, **kwargs)
        delta = time.time() - start
        logger.debug(f"{name} {delta:,.4f} s")
        return output
    return wrapper
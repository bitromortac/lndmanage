"""
Module for printing lightning channels.
"""

import math
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Tuple, List, Dict
import time

if TYPE_CHECKING:
    from lndmanage.lib.node import LndNode

from lndmanage.lib.forwardings import (
    get_channel_properties,
    get_node_properites,
)
from lndmanage import settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# define symbols for bool to string conversion
POSITIVE_MARKER = "\u2713"
NEGATIVE_MARKER = "\u2717"
ALIAS_LENGTH = 25
ANNOTATION_LENGTH = 25

PRINT_CHANNELS_FORMAT = {
    "act": {
        "dict_key": "active",
        "description": "channel is active",
        "width": 3,
        "format": "^3",
        "align": ">",
        "convert": lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    "age": {
        "dict_key": "age",
        "description": "channel age [days]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "alias": {
        "dict_key": "alias",
        "description": "alias",
        "width": ALIAS_LENGTH,
        "format": ".<" + str(ALIAS_LENGTH),
        "align": "^",
        "convert": lambda x: alias_cutoff(x),
    },
    "annotation": {
        "dict_key": "annotation",
        "description": "channel annotation",
        "width": ANNOTATION_LENGTH,
        "format": ".<" + str(ANNOTATION_LENGTH),
        "align": "^",
        "convert": lambda x: alias_cutoff(x),
    },
    "atb": {
        "dict_key": "amount_to_balanced",
        "description": "amount to be balanced (local side) [sat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "bwd": {
        "dict_key": "bandwidth_demand",
        "description": "bandwidth demand: capacity / max(mean_in, mean_out)",
        "width": 5,
        "format": "5.2f",
        "align": ">",
    },
    "cap": {
        "dict_key": "capacity",
        "description": "channel capacity [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "cid": {
        "dict_key": "chan_id",
        "description": "channel id",
        "width": 18,
        "format": "",
        "align": "^",
    },
    "fees": {
        "dict_key": "fees_out",
        "description": "total fees [sat]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "fio": {
        "dict_key": "fees_in_out",
        "description": "total fees in and out [sat]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "fo/w": {
        "dict_key": "fees_out_per_week",
        "description": "total fees out per week [sat / week]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "fi/w": {
        "dict_key": "fees_in_per_week",
        "description": "total fees in per week [sat / week]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "nfwd/a": {
        "dict_key": "forwardings_per_channel_age",
        "description": "number of forwardings per channel age in forwarding interval [1 / days]",
        "width": 6,
        "format": "6.2f",
        "align": ">",
    },
    "flow": {
        "dict_key": "flow_direction",
        "description": "flow direction (positive is outwards)",
        "width": 5,
        "format": "5.2f",
        "align": ">",
        # 'convert': lambda x: '>'*int(nan_to_zero(x)*10/3.0) if x > 0 else
        # '<'*(-int(nan_to_zero(x)*10/3.0))
    },
    "pbf": {
        "dict_key": "peer_base_fee",
        "description": "peer base fee [msat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "pfr": {
        "dict_key": "peer_fee_rate",
        "description": "peer fee rate",
        "width": 8,
        "format": "1.6f",
        "align": ">",
        "convert": lambda x: x / 1e6,
    },
    "lbf": {
        "dict_key": "local_base_fee",
        "description": "local base fee [msat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lfr": {
        "dict_key": "local_fee_rate",
        "description": "local fee rate [sat/sat]",
        "width": 8,
        "format": "1.6f",
        "align": ">",
        "convert": lambda x: x / 1e6,
    },
    "lup": {
        "dict_key": "last_update",
        "description": "last update time [days ago]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lupp": {
        "dict_key": "last_update_peer",
        "description": "last update time by peer [days ago]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lupl": {
        "dict_key": "last_update_local",
        "description": "last update time by local [days ago]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lb": {
        "dict_key": "local_balance",
        "description": "local balance [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "nfwd": {
        "dict_key": "number_forwardings",
        "description": "number of forwardings",
        "width": 4,
        "format": "4.0f",
        "align": ">",
    },
    "priv": {
        "dict_key": "private",
        "description": "channel is private",
        "width": 5,
        "format": "^5",
        "align": ">",
        "convert": lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    "r": {
        "dict_key": "action_required",
        "description": "action is required",
        "width": 1,
        "format": "^1",
        "align": ">",
        "convert": lambda x: NEGATIVE_MARKER if x else "",
    },
    "rb": {
        "dict_key": "remote_balance",
        "description": "remote balance [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "in": {
        "dict_key": "total_forwarding_in",
        "description": "total forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "ini": {
        "dict_key": "initiator",
        "description": "true if we opened channel",
        "width": 3,
        "format": "^3",
        "align": ">",
        "convert": lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    "tot": {
        "dict_key": "total_forwarding",
        "description": "total forwarding [sat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "ub": {
        "dict_key": "unbalancedness",
        "description": "unbalancedness [-1 ... 1] (0 is 50:50 balanced)",
        "width": 5,
        "format": "5.2f",
        "align": ">",
    },
    "ulr": {
        "dict_key": "uptime_lifetime_ratio",
        "description": "ratio of uptime to lifetime of channel [0 ... 1]",
        "width": 5,
        "format": "5.2f",
        "align": ">",
    },
    "imed": {
        "dict_key": "median_forwarding_in",
        "description": "median forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "imean": {
        "dict_key": "mean_forwarding_in",
        "description": "mean forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "imax": {
        "dict_key": "largest_forwarding_amount_in",
        "description": "largest forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "omed": {
        "dict_key": "median_forwarding_out",
        "description": "median forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "omean": {
        "dict_key": "mean_forwarding_out",
        "description": "mean forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "omax": {
        "dict_key": "largest_forwarding_amount_out",
        "description": "largest forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "out": {
        "dict_key": "total_forwarding_out",
        "description": "total forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "sr/w": {
        "dict_key": "sent_received_per_week",
        "description": "sent and received per week [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
}

PRINT_PEERS_FORMAT = {
    "alias": {
        "dict_key": "alias",
        "description": "alias",
        "width": ALIAS_LENGTH,
        "format": ".<" + str(ALIAS_LENGTH),
        "align": "^",
        "convert": lambda x: alias_cutoff(x),
    },
    "cap": {
        "dict_key": "total_capacity",
        "description": "total capacity [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "mpc": {
        "dict_key": "max_public_capacity",
        "description": "maximum public channel capacity [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "nid": {
        "dict_key": "node_id",
        "description": "node id",
        "width": 66,
        "format": "",
        "align": "^",
    },
    "flow": {
        "dict_key": "flow_direction",
        "description": "flow direction (positive is outwards)",
        "width": 5,
        "format": "5.2f",
        "align": ">",
    },
    "fio": {
        "dict_key": "fees_in_out",
        "description": "total fees in and out [sat]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "fo/w": {
        "dict_key": "fees_out_per_week",
        "description": "total fees out per week [sat / week]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "fi/w": {
        "dict_key": "fees_in_per_week",
        "description": "total fees per in week [sat / week]",
        "width": 7,
        "format": "7.2f",
        "align": ">",
        "convert": lambda x: float(x) / 1000,
    },
    "nc": {
        "dict_key": "number_channels",
        "description": "number of channels",
        "width": 2,
        "format": "2d",
        "align": "<",
    },
    "np": {
        "dict_key": "number_private_channels",
        "description": "number of private channels",
        "width": 2,
        "format": "2d",
        "align": "<",
    },
    "na": {
        "dict_key": "number_active_channels",
        "description": "number of active channels",
        "width": 2,
        "format": "2d",
        "align": "<",
    },
    "mlb": {
        "dict_key": "max_local_balance",
        "description": "maximal local balance [sat]",
        "width": 8,
        "format": "8d",
        "align": ">",
    },
    "mrb": {
        "dict_key": "max_remote_balance",
        "description": "maximal remote balance [sat]",
        "width": 8,
        "format": "8d",
        "align": ">",
    },
    "lbf": {
        "dict_key": "local_base_fee",
        "description": "median local base fee [msat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lfr": {
        "dict_key": "local_fee_rate",
        "description": "median local fee rate",
        "width": 8,
        "format": "1.6f",
        "align": ">",
        "convert": lambda x: x / 1e6,
    },
    "lup": {
        "dict_key": "last_update",
        "description": "last update time [days ago]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lupp": {
        "dict_key": "last_update_peer",
        "description": "last update time by peer [days ago]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lupl": {
        "dict_key": "last_update_local",
        "description": "last update time by local [days ago]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "lb": {
        "dict_key": "local_balance",
        "description": "total local balance [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "nfwd": {
        "dict_key": "number_forwardings",
        "description": "number of forwardings",
        "width": 4,
        "format": "4.0f",
        "align": ">",
    },
    "priv": {
        "dict_key": "private",
        "description": "channel is private",
        "width": 5,
        "format": "^5",
        "align": ">",
        "convert": lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    "rb": {
        "dict_key": "remote_balance",
        "description": "total remote balance [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "r": {
        "dict_key": "routable",
        "description": "all channels are routable (active and at least one public channel)",
        "width": 1,
        "format": "^1",
        "align": ">",
        "convert": lambda x: NEGATIVE_MARKER if x else "",
    },
    "in": {
        "dict_key": "total_forwarding_in",
        "description": "total forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "ini": {
        "dict_key": "initiator",
        "description": "true if we opened channel",
        "width": 3,
        "format": "^3",
        "align": ">",
        "convert": lambda x: POSITIVE_MARKER if x else NEGATIVE_MARKER,
    },
    "tot": {
        "dict_key": "total_forwarding",
        "description": "total forwarding [sat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "ub": {
        "dict_key": "unbalancedness",
        "description": "unbalancedness [-1 ... 1] (0 is 50:50 balanced)",
        "width": 5,
        "format": "5.2f",
        "align": ">",
    },
    "ulr": {
        "dict_key": "uptime_lifetime_ratio",
        "description": "ratio of uptime to lifetime of channel [0 ... 1]",
        "width": 5,
        "format": "5.2f",
        "align": ">",
    },
    "imed": {
        "dict_key": "median_forwarding_in",
        "description": "median forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "imean": {
        "dict_key": "mean_forwarding_in",
        "description": "mean forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "imax": {
        "dict_key": "largest_forwarding_amount_in",
        "description": "largest forwarding inwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "omed": {
        "dict_key": "median_forwarding_out",
        "description": "median forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "omean": {
        "dict_key": "mean_forwarding_out",
        "description": "mean forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "omax": {
        "dict_key": "largest_forwarding_amount_out",
        "description": "largest forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "out": {
        "dict_key": "total_forwarding_out",
        "description": "total forwarding outwards [sat]",
        "width": 10,
        "format": "10.0f",
        "align": ">",
    },
    "sr/w": {
        "dict_key": "sent_received_per_week",
        "description": "sent and received per week [sat]",
        "width": 9,
        "format": "9d",
        "align": ">",
    },
    "rbf": {
        "dict_key": "remote_base_fee",
        "description": "median remote base fee [msat]",
        "width": 5,
        "format": "5.0f",
        "align": ">",
    },
    "rfr": {
        "dict_key": "remote_fee_rate",
        "description": "median remote fee rate",
        "width": 8,
        "format": "1.6f",
        "align": ">",
        "convert": lambda x: x / 1e6,
    },
}


def alias_cutoff(alias: str) -> str:
    """Cuts off the node alias at a certain length and removes unicode
    characters from the node alias."""

    if len(alias) > ALIAS_LENGTH:
        return alias[: ALIAS_LENGTH - 3] + "..."
    else:
        return alias


def _sorting_order(sort_string: str) -> Tuple[str, bool]:
    """Determines the sorting string and the sorting order.

    If sort_string starts with 'rev_', the sorting order is reversed."""

    reverse_sorting = True
    if sort_string[:4] == "rev_":
        reverse_sorting = False
        sort_string = sort_string[4:]

    sort_string = PRINT_CHANNELS_FORMAT[sort_string]["dict_key"]

    return sort_string, reverse_sorting


def _row_string(column_values: Dict, print_format: Dict, columns: List[str]):
    """Constructs the formatted row string for table printing."""

    string = ""
    for column in columns:
        format_string = print_format[column]["format"]
        conversion_function = print_format[column].get("convert", lambda x: x)
        value = column_values[print_format[column]["dict_key"]]
        converted_value = conversion_function(value)
        string += f"{converted_value:{format_string}} "

    return string


def _print_objects(objects: Dict, print_format: Dict, columns: str, sort_dict: Dict):
    """General purpose node/channel printing."""

    if not objects:
        logger.info(">>> Did not find any channels.")

    objects = OrderedDict(
        sorted(objects.items(), key=sort_dict["function"], reverse=sort_dict["reverse"])
    )

    logger.info("Sorting channels by %s.", sort_dict["string"])

    logger.info("-------- Description --------")
    columns = columns.split(",")
    for column in columns:
        logger.info("%-10s %s", column, print_format[column]["description"])
    logger.info("-----------------------------")
    # prepare the column header
    column_header = ""
    for column in columns:
        column_label = print_format[column]["align"]
        column_width = print_format[column]["width"]
        column_header += f"{column:{column_label}{column_width}} "

    # print the channel data
    for channel_number, (_, channel_data) in enumerate(objects.items()):
        if not channel_number % 20:
            logger.info(column_header)
        row = _row_string(channel_data, print_format, columns)
        logger.info(row)


class ListChannels(object):
    """A class to list lightning channels."""

    def __init__(self, node: "LndNode"):
        self.node = node

    def print_all_channels(self, sort_string="rev_alias"):
        """Prints all active and inactive channels."""
        channels = self._add_channel_annotations(self.node.get_all_channels())
        sort_string, reverse_sorting = _sorting_order(sort_string)
        sort_dict = {
            "function": lambda x: (
                x[1][PRINT_CHANNELS_FORMAT["priv"]["dict_key"]],
                x[1][sort_string],
            ),
            "string": sort_string,
            "reverse": reverse_sorting,
        }
        _print_objects(
            channels,
            PRINT_CHANNELS_FORMAT,
            columns="cid,priv,act,ub,cap,lb,rb,lbf,lfr,annotation,alias",
            sort_dict=sort_dict,
        )

    def print_channels_unbalanced(self, unbalancedness: float, sort_string="rev_ub"):
        """Prints unbalanced channels with |unbalancedness(channel)| > unbalancedness."""
        channels = self._add_channel_annotations(
            self.node.get_unbalanced_channels(unbalancedness)
        )
        sort_string, reverse_sorting = _sorting_order(sort_string)
        sort_dict = {
            "function": lambda x: x[1][sort_string],
            "string": sort_string,
            "reverse": reverse_sorting,
        }
        _print_objects(
            channels,
            PRINT_CHANNELS_FORMAT,
            columns="cid,ub,cap,lb,rb,pbf,pfr,annotation,alias",
            sort_dict=sort_dict,
        )

    def print_channels_inactive(self, sort_string="lupp"):
        """Prints all inactive channels."""
        channels = self._add_channel_annotations(self.node.get_inactive_channels())
        sort_string, reverse_sorting = _sorting_order(sort_string)
        sort_dict = {
            "function": lambda x: (-x[1]["private"], x[1][sort_string]),
            "string": sort_string,
            "reverse": reverse_sorting,
        }

        _print_objects(
            channels,
            PRINT_CHANNELS_FORMAT,
            columns="cid,lupp,ulr,priv,ini,age,ub,cap,lb,rb,sr/w,annotation,alias",
            sort_dict=sort_dict,
        )

    def print_channels_forwardings(
        self, time_interval_start: float, time_interval_end: float, sort_string: str
    ):
        """Prints forwarding statistics for each channel.

        :param time_interval_start: int
        :param time_interval_end: int
        :param sort_string: str
        """
        channels = get_channel_properties(
            self.node, time_interval_start, time_interval_end
        )
        channels = self._add_channel_annotations(channels)
        sort_string, reverse_sorting = _sorting_order(sort_string)
        sort_dict = {
            "function": lambda x: (
                float("inf") if math.isnan(x[1][sort_string]) else x[1][sort_string],
                x[1][PRINT_CHANNELS_FORMAT["nfwd"]["dict_key"]],
                x[1][PRINT_CHANNELS_FORMAT["ub"]["dict_key"]],
            ),
            "string": sort_string,
            "reverse": reverse_sorting,
        }
        _print_objects(
            channels,
            PRINT_CHANNELS_FORMAT,
            columns="cid,nfwd,age,fees,fo/w,fi/w,flow,ub,bwd,r,"
            "cap,pbf,pfr,annotation,alias",
            sort_dict=sort_dict,
        )

    def print_channels_hygiene(self, time_interval_start: float, sort_string: str):
        """Prints hygiene statistics for each channel."""
        time_interval_end = time.time()
        channels = get_channel_properties(
            self.node, time_interval_start, time_interval_end
        )
        channels = self._add_channel_annotations(channels)
        sort_string, reverse_sorting = _sorting_order(sort_string)
        sort_dict = {
            "function": lambda x: x[1][sort_string],
            "string": sort_string,
            "reverse": reverse_sorting,
        }
        _print_objects(
            channels,
            PRINT_CHANNELS_FORMAT,
            columns="cid,age,ini,nfwd/a,nfwd,fo/w,ulr,lb,cap,lfr,pfr,annotation,alias",
            sort_dict=sort_dict,
        )

    def _add_channel_annotations(self, channels: Dict) -> Dict:
        """Appends metadata to existing channel dicts from the configuration file."""
        if self.node.config:
            logger.debug("Adding annotations from file %s.", self.node.config_file)
        # mapping between the channel point and channel id
        channel_point_mapping = {
            k: v["channel_point"].split(":")[0] for k, v in channels.items()
        }
        # only read annotations if config file is given
        if self.node.config_file:
            config = settings.read_config(self.node.config_file)
            annotations = config["annotations"]
        else:
            annotations = {}
        channel_annotations_funding_id = {}
        channel_annotations_channel_id = {}

        for chan_id, annotation in annotations.items():
            if len(chan_id) == 18 and chan_id.isnumeric():
                # valid channel id
                channel_annotations_channel_id[int(chan_id)] = annotation
            elif len(chan_id) == 64 and chan_id.isalnum():
                # valid funding transaction id
                channel_annotations_funding_id[chan_id] = annotation
            else:
                raise ValueError(
                    "First part needs to be either a channel id or the "
                    "funding transaction id. \n"
                    "The funding transaction id can be found with "
                    "`lncli listchannels` under the channel point (the "
                    "characters before the colon)."
                )

        for channel_id, channel_values in channels.items():
            # get the annotation by channel id first
            annotation = channel_annotations_channel_id.get(channel_id, None)
            # if no channel annotation, try with funding id
            if annotation is None:
                annotation = channel_annotations_funding_id.get(
                    channel_point_mapping[channel_id], None
                )

            if annotation is not None:
                channels[channel_id]["annotation"] = annotation
            else:
                channels[channel_id]["annotation"] = ""

        return channels

    @staticmethod
    def _row_string(column_values, columns):
        """
        Constructs the formatted row string for table printing.

        :param column_values: dict
        :param columns: list of str
        :return: formatted str
        """

        string = ""
        for column in columns:
            format_string = PRINT_CHANNELS_FORMAT[column]["format"]
            conversion_function = PRINT_CHANNELS_FORMAT[column].get(
                "convert", lambda x: x
            )
            value = column_values[PRINT_CHANNELS_FORMAT[column]["dict_key"]]
            converted_value = conversion_function(value)
            string += f"{converted_value:{format_string}} "


class ListPeers(object):
    """A class to list lightning peers (with existing channels)."""

    def __init__(self, node: "LndNode"):
        self.node = node

    def print_all_nodes(
        self,
        time_interval_start: float,
        time_interval_end: float,
        sort_string: str = "fo/w",
    ):
        """Prints nodes with forwarding statistics."""

        nodes = get_node_properites(self.node, time_interval_start, time_interval_end)

        sort_string, reverse_sorting = _sorting_order(sort_string)
        sort_dict = {
            "function": lambda x: (
                x[1][sort_string],
                x[1][PRINT_PEERS_FORMAT["mpc"]["dict_key"]],
            ),
            "string": sort_string,
            "reverse": reverse_sorting,
        }

        _print_objects(
            nodes,
            PRINT_PEERS_FORMAT,
            columns="nid,alias,nc,na,np,nfwd,flow,ub,fo/w,fi/w,mpc,lb,rb,in,out,lfr,rfr",
            sort_dict=sort_dict,
        )


if __name__ == "__main__":
    import logging.config
    from lndmanage.lib.node import LndNode

    logging.config.dictConfig(settings.logger_config)
    logger = logging.getLogger()

    nd = LndNode("/home/user/.lndmanage/config.ini")
    lp = ListPeers(nd)
    lc = ListChannels(nd)
    lp.print_all_nodes(
        time_interval_start=time.time() - 3600 * 24 * 14,
        time_interval_end=time.time(),
        sort_string="fo/w",
    )

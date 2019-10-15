"""
Creates reports for forwardings, channel opens/closings, onchain activity.
"""
import logging
from datetime import datetime
from lndmanage.lib.ln_utilities import (
    convert_channel_id_to_short_channel_id,
    height_to_timestamp
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# number of bins for histograms
NUMBER_OF_BINS = 48

# define character scale for histogram representation
# these are Braille characters, which are growing from zero to eight dots per
# character
CHARACTER_SCALE = [
    u'\u2800',
    u'\u2840',
    u'\u28C0',
    u'\u28C4',
    u'\u28E4',
    u'\u28E6',
    u'\u28F6',
    u'\u28F7',
    u'\u28FF',
]


def print_histogram(histogram_bar, unit, max_scale):
    """
    Prints a histogram over one line of text using Braille unicode chars.

    :param histogram_bar: histogram string
    :type histogram_bar: str
    :param unit: represented y unit of histogram
    :type unit: str
    :param max_scale: the maximal y size of a single bin in the histogram
    :type max_scale: int
    """
    logger.info(
        "   activity (" + CHARACTER_SCALE[8] +
        " represents %s %s):", max_scale, unit)
    logger.info("\n   %s\n", histogram_bar)


class Report(object):
    def __init__(self, node, time_start, time_end):
        """
        :param node: LND node interface
        :type node: lndmanage.lib.node.LndNode
        :param time_start: unix timestamp for beginning of analysis
        :type time_start: int
        :param time_end: unix timestamp for end of analysis
        :type time_end: int
        """
        if time_start > time_end:
            raise ValueError("starting time must be earlier than end time")

        self.node = node
        self.time_start = int(time_start)
        self.time_end = int(time_end)
        offset_days = (self.time_end - self.time_start) // 3600 // 24
        self.forwarding_events = self.node.get_forwarding_events(
            offset_days=offset_days)
        self.channel_closings = self.node.get_closed_channels()
        self.channels = self.node.get_all_channels()

    def report(self):
        """
        Prints different subreports on forwardings and channel events.
        """
        date_start = datetime.fromtimestamp(
            self.time_start).strftime('%Y-%m-%d %H:%M')
        date_end = datetime.fromtimestamp(
            self.time_end).strftime('%Y-%m-%d %H:%M')
        logger.info("\nReport from %s to %s\n", date_start, date_end)
        self.report_forwarding_events()
        logger.info("")
        self.report_forwarding_fees()
        logger.info("")
        self.report_forwarding_amounts()
        logger.info("")
        self.report_channel_closings()
        logger.info("")
        self.report_channel_openings()

    def report_forwarding_events(self):
        """
        Reports forwarding events.
        """
        series = self.get_forwarding_event_series()
        time_series = TimeSeries(series, self.time_start, self.time_end)
        histogram_bar, max_scale = time_series.histogram_bar()

        logger.info("Forwardings:")
        if time_series.total_counts:
            print_histogram(histogram_bar, "forwardings", max_scale)

            logger.info("   total forwardings: %s", time_series.total_values)
            logger.info(
                "   forwardings per day: %d",
                time_series.total_values /
                ((self.time_end - self.time_start) / (24 * 3600)))

            logger.info("\n   channels with most outgoing forwardings:")
            sorted_events_by_key = sorted(
                time_series.events_by_key.items(),
                key=lambda x: x[1]['counts'],
                reverse=True
            )
            for c in sorted_events_by_key[:5]:
                logger.info(f"   {c[0]}: {c[1]['values']}")
        else:
            logger.info("   No forwardings during this time frame.")

    def get_forwarding_event_series(self):
        """
        Fetches forwarding events in the format to be used by TimeSeries.

        :return: time series of forwarding events
        :rtype: list[dict]
        """
        series = [
            {
                'timestamp': event['timestamp'],
                'key': event['chan_id_out'],
                'quantity': 1
            }
            for event in self.forwarding_events]
        return series

    def report_forwarding_fees(self):
        """
        Reports on forwarding fees.
        """
        series = self.get_forwarding_fees_series()
        time_series = TimeSeries(series, self.time_start, self.time_end)
        histogram_bar, max_scale = time_series.histogram_bar()

        logger.info("Forwarding fees:")
        if time_series.total_counts:
            print_histogram(histogram_bar, "msat fees", max_scale)
            logger.info(
                "   total forwarding fees: %s msat", time_series.total_values)
            logger.info(
                "   fees per forwarding: %d msat",
                time_series.total_values / sum(time_series.bins_counts))

            logger.info("\n   channels with most fees collected:")
            sorted_events_by_key = sorted(
                time_series.events_by_key.items(),
                key=lambda x: x[1]['values'],
                reverse=True
            )
            for c in sorted_events_by_key[:5]:
                logger.info(f"   {c[0]}: {c[1]['values']} msat")
        else:
            logger.info("   No forwardings during this time frame.")

    def get_forwarding_fees_series(self):
        """
        Fetches forwarding fee series to be used by TimeSeries.

        :return: forwarding fee series
        :rtype: list[dict]
        """
        series = [
            {
                'timestamp': event['timestamp'],
                'key': event['chan_id_out'],
                'quantity': event['fee_msat']
            }
            for event in self.forwarding_events]
        return series

    def report_forwarding_amounts(self):
        """
        Reports forwarding amounts.
        """
        series = self.get_forwarding_amounts_series()
        time_series = TimeSeries(series, self.time_start, self.time_end)
        histogram_bar, max_scale = time_series.histogram_bar()

        logger.info("Forwarding amount:")
        if time_series.total_counts:
            print_histogram(histogram_bar, "sat", max_scale)
            logger.info("   total forwarded: %s sat", time_series.total_values)
            logger.info(
                "   amount per forwarding: %d sat",
                time_series.total_values / sum(time_series.bins_counts))

            logger.info("\n   channels with most forwarding amounts:")
            sorted_events_by_key = sorted(
                time_series.events_by_key.items(),
                key=lambda x: x[1]['values'],
                reverse=True
            )
            for c in sorted_events_by_key[:5]:
                logger.info(f"   {c[0]}: {c[1]['values']} sat")
        else:
            logger.info("   No forwardings during this time frame.")

    def get_forwarding_amounts_series(self):
        """
        Fetches forwarding amount series to be used by TimeSeries.

        :return: forwarding amount series
        :rtype: list[dict]
        """
        series = [
            {
                'timestamp': event['timestamp'],
                'key': event['chan_id_out'],
                'quantity': event['amt_out']
            }
            for event in self.forwarding_events]
        return series

    def report_channel_closings(self):
        """
        Reports channel closings.
        """
        logger.info("Channel closings:")
        series = self.get_channel_closings_series()
        time_series = TimeSeries(series, self.time_start, self.time_end)
        histogram_bar, max_scale = time_series.histogram_bar()
        if time_series.total_counts:
            print_histogram(histogram_bar, "sat", max_scale)
            logger.info("   total closings: %s", sum(time_series.bins_counts))
            logger.info("   freed funds: %s sat", sum(time_series.bins_values))

            logger.info("\n   closed channels:")
            for c in time_series.events_by_key.items():
                logger.info(f"   {c[0]}: {c[1]['values']} sat freed")
        else:
            logger.info("   No channel closings during this time frame.")

    def get_channel_closings_series(self):
        """
        Fetches forwarding amount series to be used by TimeSeries.

        :return: channel closing series
        :rtype: list[dict]
        """

        series = [
            {
                # calculate back, when approximately the channel was closed
                'timestamp': height_to_timestamp(self.node,
                                                 event['close_height']),
                'key': event_key,
                'quantity': event['settled_balance']
            }
            for event_key, event in self.channel_closings.items()]
        return series

    def report_channel_openings(self):
        """
        Reports channel openings.
        """
        logger.info("Channel openings (of current channels):")
        series = self.get_channel_openings_series()
        time_series = TimeSeries(series, self.time_start, self.time_end)
        histogram_bar, max_scale = time_series.histogram_bar()

        if time_series.total_counts:
            print_histogram(
                histogram_bar, "capacity added in sat", max_scale)

            logger.info(
                "   total openings: %s", sum(time_series.bins_counts))
            logger.info(
                "   total capacity added: %s sat",
                sum(time_series.bins_values))

            logger.info("\n   opened channels:")
            sorted_events_by_key = sorted(
                time_series.events_by_key.items(),
                key=lambda x: x[0]
            )
            for c in sorted_events_by_key:
                logger.info(f"   {c[0]}: {c[1]['values']} sat of new capacity")
        else:
            logger.info("   No channel openings during this time frame.")

    def get_channel_openings_series(self):
        """
        Fetches channel opening series to be used by TimeSeries.

        :return: channel opening series
        :rtype: list[dict]
        """
        series = []
        for chan_id, channel_values in self.channels.items():
            blockheight = convert_channel_id_to_short_channel_id(chan_id)[0]
            series.append({
                'timestamp': height_to_timestamp(self.node, blockheight),
                'key': chan_id,
                'quantity': channel_values['capacity']
            })
        return series


class TimeSeries(object):
    """
    Object to calculate time series histograms on data with special format,
    look at the above get_series methods.
    """
    def __init__(self, series, time_start, time_end):
        """
        :param series: data series
        :type series: list[dict]
        :param time_start: unix timestamp
        :type time_start: int
        :param time_end: unix timestamp
        :type time_end: int
        """
        self.series = series
        self.time_start = time_start
        self.time_end = time_end
        self.time_interval_sec = (time_end - time_start) // NUMBER_OF_BINS
        self.binned_series = []
        self.events_by_key = {}

        self.binned_series, self.events_by_key = self.create_binned_series()
        self.bins_values = list(
            map(lambda x: self.sum_data(x['data']), self.binned_series))
        self.bins_counts = list(
            map(lambda x: len(x['data']), self.binned_series))
        self.total_values = sum(self.bins_values)
        self.total_counts = sum(self.bins_counts)

    def create_binned_series(self):
        """
        Creates the histogram and analyzes the data by keys.

        :return: binned series, events by key
        :rtype: (list[dict], dict)
        """
        binned_series = []
        events_by_key = {}

        # initialize bins
        for d in range(NUMBER_OF_BINS):
            binned_series.append({
                'time_start': self.time_start + d * self.time_interval_sec,
                'time_end': self.time_start + (d + 1) * self.time_interval_sec,
                'data': []
            })

        # fill bins with key and quantity
        for s in self.series:
            _bin = (s['timestamp'] - self.time_start) // self.time_interval_sec
            if 0 <= _bin < NUMBER_OF_BINS:
                binned_series[_bin]['data'].append((s['key'], s['quantity']))

                # accumulate keyed values to have additional statistics
                if s['key'] in events_by_key:
                    events_by_key[s['key']]['counts'] += 1
                    events_by_key[s['key']]['values'] += s['quantity']
                else:
                    events_by_key[s['key']] = {
                        'counts': 1, 'values': s['quantity']}
        return binned_series, events_by_key

    def sum_data(self, data):
        """
        Sums up data in data.

        :param data: contains list of events with first index timestamp and
            second index the value of the event
        :type data: list[tuple]
        :return: data sum
        :rtype: int
        """
        s = 0
        for d in data:
            s += d[1]
        return s

    def histogram_bar(self):
        """
        Creates the histogram string from the binned data using Braille chars.

        :return: the histogram string and the maximal value of the bins
        :rtype: (str, int)
        """
        bar = '|'
        max_count = max(self.bins_values)
        # take 8 as the default max scale (Braille chars have eight dots)
        if max_count <= 8:
            max_count = 8
        # normalize to ints of maximal size of eight
        normalized_counts = [
            int(round(8 * c / max_count, 0)) for c in self.bins_values]
        # map ints to Braille characters
        for s in normalized_counts:
            bar += CHARACTER_SCALE[s]
        bar += '|'
        return bar, max_count

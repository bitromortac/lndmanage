import datetime

import matplotlib.pyplot as plt
import matplotlib.colors as colors

from lndmanage.lib.node import LndNode


def plot_forwardings(forwarding_events):
    """
    Plots a time series of the forwarding amounts.

    :param forwarding_events:
    """
    times = []
    amounts = []
    for f in forwarding_events:
        times.append(datetime.datetime.fromtimestamp(f['timestamp']))
        amounts.append(f['amt_in'])

    plt.xticks(rotation=45)
    plt.scatter(times, amounts, s=2)
    plt.yscale('log')
    plt.ylabel('Forwarding amount [sat]')
    plt.show()


def plot_fees(forwarding_events):
    """
    Plots forwarding fees and effective fee rate in color code.

    :param forwarding_events:
    """
    times = []
    amounts = []
    color = []
    for f in forwarding_events:
        times.append(datetime.datetime.fromtimestamp(f['timestamp']))
        amounts.append(f['fee_msat'])
        color.append(f['effective_fee'])
    plt.xticks(rotation=45)
    plt.scatter(times, amounts, c=color, norm=colors.LogNorm(vmin=1E-6, vmax=1E-3), s=2)
    plt.yscale('log')
    plt.ylabel('Fees [msat]')
    plt.ylim((0.5, 1E+6))
    plt.colorbar(label='effective feerate (base + rate)')
    plt.show()


def statistics_forwardings(forwarding_events):
    """
    Calculates and prints some statistics of forwarding events.

    :param forwarding_events:
    """
    total_amount = 0
    total_fees = 0
    transactions = 0
    fee_rate = 0
    channels_out = {}
    channels_in = {}

    for f in forwarding_events:
        if f['chan_id_in'] not in channels_in.keys():
            channels_in[f['chan_id_in']] = 0
        if f['chan_id_out'] not in channels_out.keys():
            channels_out[f['chan_id_out']] = 0

        channels_out[f['chan_id_out']] += f['amt_in']
        channels_in[f['chan_id_in']] += f['amt_in']

        total_amount += f['amt_in']
        total_fees += f['fee_msat']
        transactions += 1
        fee_rate += f['effective_fee']

    fee_rate /= transactions
    print("-------- Forwarding statistics --------")
    print("Number of forwardings: {}".format(transactions))
    print("Total forwardings [sat]: {}".format(total_amount))
    print("Total fees earned [sat]: {:.3f}".format(total_fees / 1000.))
    print("Average fee rate: {:.6f}".format(fee_rate))

    print("-------- Popular channels --------")
    print("Popular channels out:")
    for w in sorted(channels_out, key=channels_out.get, reverse=True)[:10]:
        print(w, channels_out[w])
    print("Popular channels in:")
    for w in sorted(channels_in, key=channels_in.get, reverse=True)[:10]:
        print(w, channels_in[w])


if __name__ == '__main__':
    node = LndNode()
    forwardings = node.get_forwarding_events()

    # plot_forwardings(forwardings)
    # plot_fees(forwardings)
    statistics_forwardings(forwardings)

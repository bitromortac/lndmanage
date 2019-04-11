import numpy as np
import matplotlib.pyplot as plt

from lib.node import LndNode


def extract_fee_settings(node):
    """
    Extracts all fee settings from the network graph.
    :return:
    list base_fees
    list fee_rates
    list time_locks
    """

    base_fees = []
    fee_rates = []
    time_locks = []

    for u, v, d in node.network.graph.edges(data=True):
        base_fees.append(d['fees']['fee_base_msat'])
        fee_rates.append(d['fees']['fee_rate_milli_msat'] / 1000000.)
        time_locks.append(d['fees']['time_lock_delta'])
    return base_fees, fee_rates, time_locks


def plot_fee_rates(fee_rates):
    exponent_min = -6
    exponent_max = 0

    bin_factor = 10

    bins_log = 10**np.linspace(
        exponent_min, exponent_max, (exponent_max - exponent_min) * bin_factor + 1)
    print(bins_log)

    plt.hist(fee_rates, bins=bins_log)
    plt.loglog()
    plt.xlabel("Fee rate bins")
    plt.ylabel("Number of channels")
    plt.show()


def plot_base_fees(base_fees):
    exponent_min = 0
    exponent_max = 5

    bin_factor = 10

    bins_log = 10**np.linspace(
        exponent_min, exponent_max, (exponent_max - exponent_min) * bin_factor + 1)
    print(bins_log)

    plt.hist(base_fees, bins=bins_log)
    plt.loglog()
    plt.xlabel("Base rate bins [msats]")
    plt.ylabel("Number of channels")
    plt.show()


def plot_cltv(time_locks):
    exponent_min = 0
    exponent_max = 3

    bin_factor = 10

    bins_log = 10**np.linspace(
        exponent_min, exponent_max, (exponent_max - exponent_min) * bin_factor + 1)
    print(bins_log)

    plt.hist(time_locks, bins=bins_log)
    plt.loglog()
    plt.xlabel("CLTV bins [blocks]")
    plt.ylabel("Number of channels")
    plt.show()


if __name__ == "__main__":
    nd = LndNode()
    base_fees, fee_rates, time_locks = extract_fee_settings(nd)

    plot_fee_rates(fee_rates)
    plot_base_fees(base_fees)
    plot_cltv(time_locks)


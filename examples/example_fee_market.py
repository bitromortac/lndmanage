import numpy as np
import matplotlib.pyplot as plt

from lndmanage.lib.node import LndNode

from matplotlib import rc

rc('text', usetex=True)
rc('font', size=8)
rc('legend', fontsize=10)
rc('text.latex', preamble=r'\usepackage{cmbright}')

# revtex column width: 246pt: 1pt = 1/72.27 inch = 8.6459 cm
standard_figsize = [8.6459/2.54, 6.5/2.54]


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
    fig, ax = plt.subplots(figsize=standard_figsize, dpi=300)
    ax.axvline(x=1E-6, c='k', ls='--')
    ax.hist(fee_rates, bins=bins_log)
    plt.loglog()
    ax.set_xlabel("Fee rate bins [sat per sat]")
    ax.set_ylabel("Number of channels")
    plt.tight_layout()
    plt.show()


def plot_base_fees(base_fees):
    exponent_min = 0
    exponent_max = 5

    bin_factor = 10

    bins_log = 10**np.linspace(
        exponent_min, exponent_max, (exponent_max - exponent_min) * bin_factor + 1)

    fig, ax = plt.subplots(figsize=standard_figsize, dpi=300)
    ax.hist(base_fees, bins=bins_log)
    ax.axvline(x=1E3, c='k', ls='--')
    plt.loglog()
    ax.set_xlabel("Base fee bins [msat]")
    ax.set_ylabel("Number of channels")
    plt.tight_layout()
    plt.show()


def plot_cltv(time_locks):
    exponent_min = 0
    exponent_max = 3

    bin_factor = 10

    bins_log = 10**np.linspace(
        exponent_min, exponent_max, (exponent_max - exponent_min) * bin_factor + 1)

    fig, ax = plt.subplots(figsize=standard_figsize, dpi=300)

    ax.hist(time_locks, bins=bins_log)
    plt.loglog()
    ax.set_xlabel("CLTV bins [blocks]")
    ax.set_ylabel("Number of channels")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    nd = LndNode('/home/user/.lndmanage/config.ini')
    base_fees, fee_rates, time_locks = extract_fee_settings(nd)

    plot_fee_rates(fee_rates)
    plot_base_fees(base_fees)
    plot_cltv(time_locks)


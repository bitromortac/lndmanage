from lib.fee_setting import FeeSetter
from lib.node import LndNode

if __name__ == '__main__':
    node = LndNode()
    fee_setter = FeeSetter(node)

    print(fee_setter.factor_demand(32, 3500000))
    print(fee_setter.factor_demand(31, 3000000))
    print(fee_setter.factor_demand(27, 2000000))
    print(fee_setter.factor_demand(18, 2500000))
    print(fee_setter.factor_demand(7, 1300000))
    print(fee_setter.factor_demand(4, 250000))
    print(fee_setter.factor_demand(4, 1000000))
    print(fee_setter.factor_demand(2, 100000))
    print(fee_setter.factor_demand(0, 100000))
    print(fee_setter.factor_demand(0.440, 1000000))

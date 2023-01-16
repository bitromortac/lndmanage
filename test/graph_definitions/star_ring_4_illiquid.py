"""Implements a complete graph, where the master node A can be thought of
being surrounded by four nodes, which share an illiquid network of channels.
The master node has unbalanced total inbound to outbound ratio.
                                  A                 1: 1_000_000 10:0
                             4.   ^   .1            2: 1_000_000  3:7
                          .    3 / r 2    .         3: 1_000_000  3:7
                      .         /   r         .     4: 1_000_000  4:6
                   E-----------------------7----B   5:   500_000  1:9
                     .   x    /       r    o6  .5   6:   500_000  5:5
                       .     x         o     .      7:   500_000  9:1
                         .   /   x o   r   .        8:   500_000  9:1
                         10.   o     x9  .          9:   500_000  1:9
                            D---------8-C          10:   500_000  5:5
"""
nodes = {
    'A': {
        'grpc_port': 11009,
        'rest_port': 8080,
        'port': 9735,
        'base_fee_msat': 1,
        'fee_rate': 0.000001,
        'channels': {
            1: {
                'to': 'B',
                'capacity': 1_000_000,
                'ratio_local': 10,
                'ratio_remote': 0,
            },
            2: {
                'to': 'C',
                'capacity': 1_000_000,
                'ratio_local': 3,
                'ratio_remote': 7,
            },
            3: {
                'to': 'D',
                'capacity': 1_000_000,
                'ratio_local': 3,
                'ratio_remote': 7,
            },
            4: {
                'to': 'E',
                'capacity': 1_000_000,
                'ratio_local': 4,
                'ratio_remote': 6,
            },
        }
    },
    'B': {
        'grpc_port': 11010,
        'rest_port': 8081,
        'port': 9736,
        'base_fee_msat': 2,
        'fee_rate': 0.000002,
        'channels': {
            5: {
                'to': 'C',
                'capacity': 500_000,
                'ratio_local': 1,
                'ratio_remote': 9,
            },
            6: {
                'to': 'D',
                'capacity': 500_000,
                'ratio_local': 5,
                'ratio_remote': 5,
            },
            7: {
                'to': 'E',
                'capacity': 500_000,
                'ratio_local': 9,
                'ratio_remote': 1,
            },
        }
    },
    'C': {
        'grpc_port': 11011,
        'rest_port': 8082,
        'port': 9737,
        'base_fee_msat': 3,
        'fee_rate': 0.000003,
        'channels': {
            8: {
                'to': 'D',
                'capacity': 500_000,
                'ratio_local': 9,
                'ratio_remote': 1,
            },
            9: {
                'to': 'E',
                'capacity': 500_000,
                'ratio_local': 1,
                'ratio_remote': 9,
            },
        }
    },
    'D': {
        'grpc_port': 11012,
        'rest_port': 8083,
        'port': 9738,
        'base_fee_msat': 4,
        'fee_rate': 0.000004,
        'channels': {
            10: {
                'to': 'E',
                'capacity': 500_000,
                'ratio_local': 5,
                'ratio_remote': 5,
            },
        }
    },
    'E': {
        'grpc_port': 11013,
        'rest_port': 8084,
        'port': 9739,
        'base_fee_msat': 2,
        'fee_rate': 0.000001,
        'channels': {
        }
    },
}

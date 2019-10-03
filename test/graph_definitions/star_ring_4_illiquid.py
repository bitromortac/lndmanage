"""
Implements a complete graph, where the master node A can be thought of
being surrounded by four nodes, which share an illiquid network of channels.
The master node has unbalanced total inbound to outbound ratio.
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
                'capacity': 1000000,
                'ratio_local': 10,
                'ratio_remote': 0,
            },
            2: {
                'to': 'C',
                'capacity': 1000000,
                'ratio_local': 3,
                'ratio_remote': 7,
            },
            3: {
                'to': 'D',
                'capacity': 1000000,
                'ratio_local': 3,
                'ratio_remote': 7,
            },
            4: {
                'to': 'E',
                'capacity': 1000000,
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
                'capacity': 500000,
                'ratio_local': 1,
                'ratio_remote': 9,
            },
            6: {
                'to': 'D',
                'capacity': 500000,
                'ratio_local': 5,
                'ratio_remote': 5,
            },
            7: {
                'to': 'E',
                'capacity': 500000,
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
                'capacity': 500000,
                'ratio_local': 9,
                'ratio_remote': 1,
            },
            9: {
                'to': 'E',
                'capacity': 500000,
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
                'capacity': 500000,
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

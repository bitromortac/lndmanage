"""
Implements a lightning network topology:
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
                'ratio_local': 5,
                'ratio_remote': 5,
            },
        }
    },
    'B': {
        'grpc_port': 11010,
        'rest_port': 8081,
        'port': 9736,
        'base_fee_msat': 2,
        'fee_rate': 0.000001,
        'channels': {
            3: {
                'to': 'C',
                'capacity': 10000000,
                'ratio_local': 5,
                'ratio_remote': 5,
            },
            4: {
                'to': 'D',
                'capacity': 10000000,
                'ratio_local': 5,
                'ratio_remote': 5,
            },
        }
    },
    'C': {
        'grpc_port': 11011,
        'rest_port': 8082,
        'port': 9737,
        'base_fee_msat': 1,
        'fee_rate': 0.000003,
        'channels': {
            5: {
                'to': 'D',
                'capacity': 1000000,
                'ratio_local': 5,
                'ratio_remote': 5,
            },
        }
    },
    'D': {
        'grpc_port': 11012,
        'rest_port': 8083,
        'port': 9738,
        'base_fee_msat': 1,
        'fee_rate': 0.000002,
        'channels': {
            6: {
                'to': 'A',
                'capacity': 1000000,
                'ratio_local': 10,
                'ratio_remote': 0,
            },
        }
    },
}

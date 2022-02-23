"""
Implements a lightning network topology:

        3
    A  ---  B
    |    2/ |
  6 |   E   | 1
    | /5 \7 |
    D  ---  C
        4

All fees are equal.

valid routes from A -> E:
A -3-> B -2-> E
A -6-> D -5-> E
A -6-> D -4-> C -7-> E
A -3-> B -1-> C -7-> E
A -6-> D -4-> C -1-> B -2-> E
A -3-> B -1-> C -4-> D -5-> E
"""

nodes = {
    'A': {
        'grpc_port': 11009,
        'rest_port': 8080,
        'port': 9735,
        'channels': {
            3: {
                'to': 'B',
                'capacity': 1_000_000,
                'ratio_local': 10,
                'ratio_remote': 0,
                'policies': {
                    'A' > 'B': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 1_000_000_000,
                    },
                    'B' > 'A': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 1_000_000_000,
                    }
                }
            },
            6: {
                'to': 'D',
                'capacity': 2_000_000,
                'ratio_local': 5,
                'ratio_remote': 5,
                'policies': {
                    'A' > 'D': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 2_000_000_000,
                    },
                    'D' > 'A': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 2_000_000_000,
                    }
                }
            },
        }
    },
    'B': {
        'grpc_port': 11010,
        'rest_port': 8081,
        'port': 9736,
        'channels': {
            2: {
                'to': 'E',
                'capacity': 3000000,
                'ratio_local': 5,
                'ratio_remote': 5,
                'policies': {
                    'B' > 'E': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 3_000_000_000,
                    },
                    'E' > 'B': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 3_000_000_000,
                    }
                }
            },
            1: {
                'to': 'C',
                'capacity': 10_000_000,
                'ratio_local': 5,
                'ratio_remote': 5,
                'policies': {
                    'B' > 'C': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 10_000_000_000,
                    },
                    'C' > 'B': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 10_000_000_000,
                    }
                }
            },
        }
    },
    'C': {
        'grpc_port': 11011,
        'rest_port': 8082,
        'port': 9737,
        'channels': {
            7: {
                'to': 'E',
                'capacity': 1_000_000,
                'ratio_local': 5,
                'ratio_remote': 5,
                'policies': {
                    'C' > 'E': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 1_000_000_000,
                    },
                    'E' > 'C': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 1_000_000_000,
                    }
                }
            },
            4: {
                'to': 'D',
                'capacity': 2000000,
                'ratio_local': 5,
                'ratio_remote': 5,
                'policies': {
                    'C' > 'D': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 2_000_000_000,
                    },
                    'D' > 'C': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 2_000_000_000,
                    }
                }
            },
        }
    },
    'D': {
        'grpc_port': 11012,
        'rest_port': 8083,
        'port': 9738,
        'channels': {
            5: {
                'to': 'E',
                'capacity': 3_000_000,
                'ratio_local': 10,
                'ratio_remote': 0,
                'policies': {
                    'D' > 'E': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 3_000_000_000,
                    },
                    'E' > 'D': {
                        'fee_base_msat': 1000,
                        'fee_rate_milli_msat': 100,
                        'time_lock_delta': 40,
                        'disabled': False,
                        'min_htlc': 0,
                        'max_htlc_msat': 3_000_000_000,
                    }
                }
            },
        }
    },
    'E': {
        'grpc_port': 11013,
        'rest_port': 8084,
        'port': 9739,
        'channels': {
        }
    },
}

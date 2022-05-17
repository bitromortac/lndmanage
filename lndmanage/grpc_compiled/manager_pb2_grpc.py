# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

from lndmanage.grpc_compiled import manager_pb2 as manager__pb2


class MangagerStub(object):
    """blah.
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.RunningServices = channel.unary_unary(
                '/managerpc.Mangager/RunningServices',
                request_serializer=manager__pb2.RunningServicesRequest.SerializeToString,
                response_deserializer=manager__pb2.RunningServicesResponse.FromString,
                )


class MangagerServicer(object):
    """blah.
    """

    def RunningServices(self, request, context):
        """blah.
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_MangagerServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'RunningServices': grpc.unary_unary_rpc_method_handler(
                    servicer.RunningServices,
                    request_deserializer=manager__pb2.RunningServicesRequest.FromString,
                    response_serializer=manager__pb2.RunningServicesResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'managerpc.Mangager', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class Mangager(object):
    """blah.
    """

    @staticmethod
    def RunningServices(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/managerpc.Mangager/RunningServices',
            manager__pb2.RunningServicesRequest.SerializeToString,
            manager__pb2.RunningServicesResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

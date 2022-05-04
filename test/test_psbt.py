from binascii import a2b_base64
from unittest import TestCase

from lndmanage.lib import psbt


class PSBTTest(TestCase):
    def test_psbt_magic(self):
        self.assertEqual(bytes.fromhex('70736274FF'), psbt.PSBT_MAGIC_SEPARATOR)

    def test_psbt_from_bytes(self):
        data = a2b_base64("cHNidP8BAIkCAAAAAW18fk+d7Xn+uwhZbaB+QqCAL8hJH58FShnRPbJnEuBtAAAAAAD/////Asef/AEAAAAAIgAgd/G0Fd8Bj6JPRZe3l0jTyNymOS+MzCuF6R6afTUJlb+QP/kDAAAAACIAIHm/fFMVYD11fLjoRMGLYFCkqP8XnFKusmHfstlELelHAAAAAAABAN4CAAAAAAEBPVfLJjNQObnakrPrX7dFrViGGPhbdTLQdAZg8FLeMvYBAAAAAP7///8CAOH1BQAAAAAWABS6BvZzsfWYFhsFXzaUDQhHnBfRddmXgR0BAAAAFgAUV4AyH5gnj5MPgyOVERAkgpMp0mUCRzBEAiAOXvriTqHmFxWv6sBKPhNnsToTr24xUssEEKvI2orduQIgUjbrfAFSIDWWhe8WXwTbMeWB9IoHevu1snICGsAMoucBIQJ21ss2GSM0fV8F3ILVqzW3SNdunSNjSNh1CGQuqwq7q78AAAABAR8A4fUFAAAAABYAFLoG9nOx9ZgWGwVfNpQNCEecF9F1AQMEAQAAACIGA0DnWsAOWoFkVk9RVhWWV95PWI8PEuaT5EcT403nRwFMGAAAAABUAACAAAAAgAAAAIAAAAAABQAAAAAAAA==")
        num_inputs, num_outputs, amounts = psbt.extract_psbt_inputs_outputs(data)
        self.assertEqual((1, 2, [33333191, 66666384]), (num_inputs, num_outputs, amounts))

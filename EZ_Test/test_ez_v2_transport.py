import asyncio
import unittest

from EZ_V2.network_transport import TCPNetworkTransport, decode_envelope, encode_envelope
from EZ_V2.networking import NetworkEnvelope


class EZV2TransportTests(unittest.TestCase):
    def test_envelope_roundtrip(self) -> None:
        envelope = NetworkEnvelope(
            msg_type="chain_state_req",
            sender_id="account-1",
            recipient_id="consensus-1",
            payload={"height": 7},
        )
        decoded = decode_envelope(encode_envelope(envelope))
        self.assertEqual(decoded.msg_type, envelope.msg_type)
        self.assertEqual(decoded.sender_id, envelope.sender_id)
        self.assertEqual(decoded.recipient_id, envelope.recipient_id)
        self.assertEqual(decoded.payload, envelope.payload)

    def test_tcp_transport_send_receive(self) -> None:
        async def scenario() -> None:
            server = TCPNetworkTransport("127.0.0.1", 19781)
            client = TCPNetworkTransport("127.0.0.1", 19782)

            async def handler(envelope: NetworkEnvelope, remote: str):
                return {
                    "ok": True,
                    "echo_type": envelope.msg_type,
                    "sender_id": envelope.sender_id,
                    "remote": remote,
                }

            server.set_handler(handler)

            async def noop_handler(envelope: NetworkEnvelope, remote: str):
                return {"ok": True}

            client.set_handler(noop_handler)

            try:
                await server.start()
                await client.start()
            except PermissionError as exc:
                raise unittest.SkipTest(f"bind_not_permitted:{exc}") from exc
            try:
                response = await client.send(
                    "127.0.0.1:19781",
                    NetworkEnvelope(
                        msg_type="bundle_submit",
                        sender_id="account-1",
                        recipient_id="consensus-1",
                        payload={"seq": 1},
                    ),
                )
                assert response is not None
                self.assertTrue(response["ok"])
                self.assertEqual(response["echo_type"], "bundle_submit")
                self.assertEqual(response["sender_id"], "account-1")
            finally:
                await client.stop()
                await server.stop()

        asyncio.run(scenario())

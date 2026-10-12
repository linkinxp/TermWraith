import asyncio
import socket

import asyncssh

REPLY_OK = b"\x05\x00\x00\x01" + bytes(6)
REPLY_REFUSED = b"\x05\x05\x00\x01" + bytes(6)
REPLY_UNSUPPORTED = b"\x05\x07\x00\x01" + bytes(6)


async def serve(conn: asyncssh.SSHClientConnection, port: int) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            _, methods = await reader.readexactly(2)
            await reader.readexactly(methods)
            writer.write(b"\x05\x00")
            ver, cmd, _, atyp = await reader.readexactly(4)
            if ver != 5 or cmd != 1:
                writer.write(REPLY_UNSUPPORTED)
                return
            if atyp == 1:
                host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
            elif atyp == 3:
                host = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
            else:
                writer.write(REPLY_UNSUPPORTED)
                return
            target_port = int.from_bytes(await reader.readexactly(2), "big")
            try:
                remote_reader, remote_writer = await conn.open_connection(host, target_port)
            except (OSError, asyncssh.Error):
                writer.write(REPLY_REFUSED)
                return
            writer.write(REPLY_OK)
            await writer.drain()
            await asyncio.gather(_pipe(reader, remote_writer), _pipe(remote_reader, writer))
        except (asyncio.IncompleteReadError, OSError, asyncssh.Error):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


async def _pipe(source, destination) -> None:
    try:
        while data := await source.read(65536):
            destination.write(data)
            await destination.drain()
    except (OSError, asyncssh.Error):
        pass
    finally:
        destination.close()

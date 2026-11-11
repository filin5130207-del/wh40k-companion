from __future__ import annotations

import argparse
import select
import socket
import threading


def pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            r, _, _ = select.select([a], [], [], 60)
            if not r:
                break
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def handle(client: socket.socket, upstream_host: str, upstream_port: int) -> None:
    try:
        upstream = socket.create_connection((upstream_host, upstream_port), timeout=10)
    except OSError:
        client.close()
        return
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    pipe(upstream, client)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--listen-host', default='192.168.0.163')
    p.add_argument('--listen-port', type=int, default=8069)
    p.add_argument('--upstream-host', default='127.0.0.1')
    p.add_argument('--upstream-port', type=int, default=8069)
    args = p.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.listen_host, args.listen_port))
    srv.listen(64)
    print(
        f'LAN proxy listening on http://{args.listen_host}:{args.listen_port} '
        f'-> {args.upstream_host}:{args.upstream_port}',
        flush=True,
    )
    while True:
        client, _addr = srv.accept()
        threading.Thread(
            target=handle,
            args=(client, args.upstream_host, args.upstream_port),
            daemon=True,
        ).start()


if __name__ == '__main__':
    main()

from __future__ import annotations

import pickle
import struct
import sys

import numpy as np
from ortools.graph.python import min_cost_flow


class SidecarProtocolError(Exception):
    pass


def _read_exact(stream, byte_count: int) -> bytes:
    data = bytearray()
    while len(data) < byte_count:
        chunk = stream.read(byte_count - len(data))
        if not chunk:
            raise EOFError('Unexpected EOF while reading sidecar message')
        data.extend(chunk)
    return bytes(data)


def _read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise SidecarProtocolError('Incomplete sidecar message header')
    (size,) = struct.unpack('<I', header)
    payload = _read_exact(stream, size)
    return pickle.loads(payload)


def _write_message(stream, obj) -> None:
    payload = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack('<I', len(payload)))
    stream.write(payload)
    stream.flush()


def _solve(payload: dict) -> dict:
    smcf = min_cost_flow.SimpleMinCostFlow()
    start_nodes = np.asarray(payload['start_nodes'], dtype=np.int64)
    end_nodes = np.asarray(payload['end_nodes'], dtype=np.int64)
    capacities = np.asarray(payload['capacities'], dtype=np.int64)
    unit_costs = np.asarray(payload['unit_costs'], dtype=np.int64)
    node_supplies = np.asarray(payload['node_supplies'], dtype=np.int64)
    all_arcs = smcf.add_arcs_with_capacity_and_unit_cost(start_nodes, end_nodes, capacities, unit_costs)
    smcf.set_nodes_supplies(np.arange(len(node_supplies), dtype=np.int64), node_supplies)
    status = int(smcf.solve())
    result = {
        'status': status,
        'optimal_status': int(smcf.OPTIMAL),
        'flows': [],
        'optimal_cost': None,
    }
    if status == int(smcf.OPTIMAL):
        result['flows'] = [int(value) for value in smcf.flows(all_arcs)]
        result['optimal_cost'] = int(smcf.optimal_cost())
    return result


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        request = _read_message(stdin)
        if request is None:
            return 0
        command = request.get('command')
        if command == 'shutdown':
            _write_message(stdout, {'ok': True})
            return 0
        if command != 'solve':
            _write_message(stdout, {'error': f'Unknown command {command!r}'})
            continue
        try:
            response = _solve(request)
        except Exception as ex:
            _write_message(stdout, {'error': f'{type(ex).__name__}: {ex}'})
            continue
        _write_message(stdout, response)


if __name__ == '__main__':
    raise SystemExit(main())

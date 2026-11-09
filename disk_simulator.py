
from dataclasses import dataclass

@dataclass
class IORequest:
    track: int
    operation: str = "READ"
    description: str = ""

@dataclass
class SchedulingResult:
    order: list
    movements: list
    total_movement: int

class FCFSScheduler:
    @staticmethod
    def schedule(requests, initial_head):
        current = initial_head
        order = [initial_head]
        movements = []

        for request in requests:
            movements.append(abs(current - request.track))
            order.append(request.track)
            current = request.track

        return SchedulingResult(order, movements, sum(movements))

class SimulatedDisk:
    def __init__(self, disk_id, block_size=4096):
        if block_size <= 0:
            raise ValueError("Tamanho de bloco inválido")
        self.disk_id = disk_id
        self.block_size = block_size
        self.blocks = {}
        self.online = True

    def write_block(self, physical_block, data):
        if not self.online:
            raise IOError(f"Disco {self.disk_id} indisponível")
        if len(data) != self.block_size:
            raise ValueError("Tamanho de bloco inválido")
        self.blocks[physical_block] = bytes(data)

    def read_block(self, physical_block):
        if not self.online:
            raise IOError(f"Disco {self.disk_id} indisponível")
        return self.blocks.get(physical_block, bytes(self.block_size))

class RAID5:
    def __init__(self, disk_count=3, block_size=4096):
        if disk_count < 3:
            raise ValueError("RAID 5 exige pelo menos 3 discos")
        self.disk_count = disk_count
        self.block_size = block_size
        self.disks = [SimulatedDisk(i, block_size) for i in range(disk_count)]
        self.data_disks_per_stripe = disk_count - 1
        self.known_stripes = set()

    def parity_disk(self, stripe):
        return self.disk_count - 1 - (stripe % self.disk_count)

    def data_disk_order(self, stripe):
        parity = self.parity_disk(stripe)
        return [i for i in range(self.disk_count) if i != parity]

    def locate_block(self, logical_block):
        if logical_block < 0:
            raise ValueError("Bloco lógico inválido")
        stripe = logical_block // self.data_disks_per_stripe
        index = logical_block % self.data_disks_per_stripe
        return stripe, self.data_disk_order(stripe)[index]

    @staticmethod
    def xor_blocks(blocks, block_size):
        result = bytearray(block_size)
        for block in blocks:
            for i, value in enumerate(block):
                result[i] ^= value
        return bytes(result)

    def write_block(self, logical_block, data):
        if len(data) != self.block_size:
            raise ValueError("Tamanho de bloco inválido")
        if any(not disk.online for disk in self.disks):
            raise IOError("Não é possível gravar com disco indisponível")

        stripe, target_disk = self.locate_block(logical_block)
        data_order = self.data_disk_order(stripe)
        stripe_data = []

        for index, disk_id in enumerate(data_order):
            if disk_id == target_disk:
                stripe_data.append(bytes(data))
            else:
                other_logical = stripe * self.data_disks_per_stripe + index
                stripe_data.append(self.read_block(other_logical))

        for disk_id, block in zip(data_order, stripe_data):
            self.disks[disk_id].write_block(stripe, block)

        parity = self.xor_blocks(stripe_data, self.block_size)
        self.disks[self.parity_disk(stripe)].write_block(stripe, parity)
        self.known_stripes.add(stripe)

    def read_block(self, logical_block):
        stripe, target_disk = self.locate_block(logical_block)

        if self.disks[target_disk].online:
            return self.disks[target_disk].read_block(stripe)

        available = []
        for disk in self.disks:
            if disk.disk_id == target_disk:
                continue
            if not disk.online:
                raise IOError("RAID 5 não suporta falha simultânea de dois discos")
            available.append(disk.read_block(stripe))

        return self.xor_blocks(available, self.block_size)

    def write(self, data, start_lba=0):
        if start_lba < 0:
            raise ValueError("Endereço lógico inválido")
        results = []
        for offset in range(0, len(data), self.block_size):
            chunk = data[offset:offset + self.block_size].ljust(self.block_size, b"\x00")
            logical_block = start_lba + offset // self.block_size
            self.write_block(logical_block, chunk)
            results.append(self.locate_block(logical_block))
        return results

    def read(self, size, start_lba=0):
        if size < 0 or start_lba < 0:
            raise ValueError("Parâmetros inválidos")
        output = bytearray()
        count = (size + self.block_size - 1) // self.block_size
        for offset in range(count):
            output.extend(self.read_block(start_lba + offset))
        return bytes(output[:size])

    def fail_disk(self, disk_id):
        self.validate_disk_id(disk_id)
        self.disks[disk_id].online = False

    def rebuild_disk(self, disk_id):
        self.validate_disk_id(disk_id)
        failed = [disk for disk in self.disks if not disk.online]

        if len(failed) != 1 or self.disks[disk_id].online:
            raise IOError("A reconstrução exige exatamente um disco indisponível")

        target = self.disks[disk_id]
        for stripe in self.known_stripes:
            blocks = [disk.read_block(stripe) for disk in self.disks if disk.disk_id != disk_id]
            target.blocks[stripe] = self.xor_blocks(blocks, self.block_size)

        target.online = True

    def validate_disk_id(self, disk_id):
        if not 0 <= disk_id < self.disk_count:
            raise ValueError("Identificador de disco inválido")

class CANDecoder:
    def decode(self, arbitration_id: int, data: bytes):
        return {
            "id": hex(arbitration_id),
            "dlc": len(data),
            "raw": data.hex()
        }

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest

from democracy.funding.bitcoin_tx import (
    BitcoinTransaction,
    TxFormatError,
    TxInput,
    TxOutput,
    _encode_varint,
    _read_exact,
    _read_uint32_le,
    _read_uint64_le,
    _read_varint,
    _uint32_le,
    _uint64_le,
    combine_anyonecanpay_pledges,
    parse_transaction,
)


def _make_legacy_transaction() -> BitcoinTransaction:
    return BitcoinTransaction(
        version=2,
        inputs=[
            TxInput(
                prev_txid_le=bytes.fromhex(
                    "000102030405060708090a0b0c0d0e0f"
                    "101112131415161718191a1b1c1d1e1f"
                ),
                vout=3,
                script_sig=bytes.fromhex("512102"),
                sequence=0xFFFFFFFE,
                witness=[],
            )
        ],
        outputs=[
            TxOutput(
                value_sats=50_000,
                script_pubkey=bytes.fromhex("5175ac"),
            )
        ],
        locktime=42,
    )


def _make_segwit_transaction(
    *,
    prev_txid_byte: int = 0xAA,
    value_sats: int = 7_000,
    witness: list[bytes] | None = None,
) -> BitcoinTransaction:
    return BitcoinTransaction(
        version=1,
        inputs=[
            TxInput(
                prev_txid_le=bytes([prev_txid_byte]) * 32,
                vout=1,
                script_sig=b"",
                sequence=0xFFFFFFFF,
                witness=witness if witness is not None else [b"\x30", b"\x01\x01"],
            )
        ],
        outputs=[
            TxOutput(
                value_sats=value_sats,
                script_pubkey=bytes.fromhex("51ac"),
            )
        ],
        locktime=0,
    )


# =========================================================
# TxInput.outpoint_key()
# =========================================================
def test_tx_input_outpoint_key_returns_big_endian_txid_and_vout() -> None:
    tx_input = TxInput(
        prev_txid_le=bytes.fromhex(
            "00112233445566778899aabbccddeefffedcba98765432100123456789abcdef"
        ),
        vout=5,
        script_sig=b"",
        sequence=0,
        witness=[],
    )

    assert tx_input.outpoint_key() == (
        "efcdab89674523011032547698badcfeffeeddccbbaa99887766554433221100",
        5,
    )


# =========================================================
# BitcoinTransaction.serialize()
# =========================================================
def test_bitcoin_transaction_serializes_legacy_transaction_to_expected_hex() -> None:
    tx = _make_legacy_transaction()

    expected_hex = (
        "0200000001"
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
        "03000000"
        "03512102"
        "feffffff"
        "01"
        "50c3000000000000"
        "03"
        "5175ac"
        "2a000000"
    )

    assert tx.to_hex() == expected_hex
    assert tx.serialize_without_witness().hex() == expected_hex


# =========================================================
# BitcoinTransaction.to_hex()
# =========================================================
def test_bitcoin_transaction_to_hex_returns_serialized_hex() -> None:
    tx = _make_legacy_transaction()

    expected_hex = (
        "0200000001"
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
        "03000000"
        "03512102"
        "feffffff"
        "01"
        "50c3000000000000"
        "03"
        "5175ac"
        "2a000000"
    )

    assert tx.to_hex() == expected_hex


# =========================================================
# BitcoinTransaction.txid()
# =========================================================
def test_txid_is_computed_from_serialization_without_witness() -> None:
    tx = _make_segwit_transaction()

    expected_txid = (
        hashlib.sha256(hashlib.sha256(tx.serialize_without_witness()).digest())
        .digest()[::-1]
        .hex()
    )

    assert tx.txid() == expected_txid
    assert (
        tx.txid()
        == BitcoinTransaction(
            version=tx.version,
            inputs=[
                TxInput(
                    prev_txid_le=tx.inputs[0].prev_txid_le,
                    vout=tx.inputs[0].vout,
                    script_sig=tx.inputs[0].script_sig,
                    sequence=tx.inputs[0].sequence,
                    witness=[],
                )
            ],
            outputs=tx.outputs,
            locktime=tx.locktime,
        ).txid()
    )


# =========================================================
# BitcoinTransaction.serialize_without_witness()
# =========================================================
def test_serialize_without_witness_omits_segwit_marker_flag_and_witness() -> None:
    tx = _make_segwit_transaction()

    assert tx.serialize_without_witness().hex() == (
        "01000000"
        "01"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "01000000"
        "00"
        "ffffffff"
        "01"
        "581b000000000000"
        "02"
        "51ac"
        "00000000"
    )


# =========================================================
# parse_transaction()
# =========================================================
def test_parse_transaction_round_trips_segwit_transaction() -> None:
    raw_tx_hex = (
        "01000000"
        "0001"
        "01"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "01000000"
        "00"
        "ffffffff"
        "01"
        "581b000000000000"
        "02"
        "51ac"
        "02"
        "01"
        "30"
        "02"
        "0101"
        "00000000"
    )

    parsed = parse_transaction(raw_tx_hex)

    assert parsed == _make_segwit_transaction()
    assert parsed.to_hex() == raw_tx_hex


@pytest.mark.parametrize(
    ("raw_tx_hex", "message"),
    [
        ("not-hex", "raw_tx_hex is not valid hex"),
        ("010000000002", "Invalid segwit transaction marker/flag"),
    ],
)
def test_parse_transaction_rejects_invalid_input(
    raw_tx_hex: str,
    message: str,
) -> None:
    with pytest.raises(TxFormatError, match=message):
        parse_transaction(raw_tx_hex)


def test_parse_transaction_rejects_truncated_transaction() -> None:
    raw_tx_hex = _make_legacy_transaction().to_hex()[:-2]

    with pytest.raises(TxFormatError, match="Unexpected end of transaction"):
        parse_transaction(raw_tx_hex)


def test_parse_transaction_rejects_trailing_bytes() -> None:
    raw_tx_hex = _make_legacy_transaction().to_hex() + "00"

    with pytest.raises(TxFormatError, match="Unexpected bytes after transaction end"):
        parse_transaction(raw_tx_hex)


# =========================================================
# combine_anyonecanpay_pledges()
# =========================================================
def test_combine_anyonecanpay_pledges_merges_inputs_into_one_transaction() -> None:
    pledge_one = _make_segwit_transaction(prev_txid_byte=0x11, witness=[b"\x30"])
    pledge_two = _make_segwit_transaction(
        prev_txid_byte=0x22, witness=[b"\x31", b"\x01"]
    )

    combined = parse_transaction(
        combine_anyonecanpay_pledges([pledge_one.to_hex(), pledge_two.to_hex()])
    )

    assert combined.version == pledge_one.version
    assert combined.locktime == pledge_one.locktime
    assert combined.outputs == pledge_one.outputs
    assert combined.inputs == [pledge_one.inputs[0], pledge_two.inputs[0]]


@pytest.mark.parametrize(
    ("pledges", "message"),
    [
        ([], "At least one pledge transaction is required"),
        (
            [
                _make_segwit_transaction(prev_txid_byte=0x11).to_hex(),
                _make_segwit_transaction(prev_txid_byte=0x11).to_hex(),
            ],
            "Duplicate pledge input",
        ),
        (
            [
                BitcoinTransaction(
                    version=1,
                    inputs=[
                        TxInput(
                            prev_txid_le=b"\x01" * 32,
                            vout=0,
                            script_sig=b"",
                            sequence=0xFFFFFFFF,
                            witness=[b"\x01"],
                        ),
                        TxInput(
                            prev_txid_le=b"\x02" * 32,
                            vout=1,
                            script_sig=b"",
                            sequence=0xFFFFFFFF,
                            witness=[b"\x02"],
                        ),
                    ],
                    outputs=_make_segwit_transaction().outputs,
                    locktime=0,
                ).to_hex()
            ],
            "exactly one input",
        ),
        (
            [
                _make_segwit_transaction(
                    prev_txid_byte=0x11, value_sats=7_000
                ).to_hex(),
                _make_segwit_transaction(
                    prev_txid_byte=0x22, value_sats=8_000
                ).to_hex(),
            ],
            "identical outputs",
        ),
        (
            [
                _make_segwit_transaction(prev_txid_byte=0x11).to_hex(),
                BitcoinTransaction(
                    version=2,
                    inputs=_make_segwit_transaction(prev_txid_byte=0x22).inputs,
                    outputs=_make_segwit_transaction(prev_txid_byte=0x22).outputs,
                    locktime=0,
                ).to_hex(),
            ],
            "same version",
        ),
        (
            [
                _make_segwit_transaction(prev_txid_byte=0x11).to_hex(),
                BitcoinTransaction(
                    version=1,
                    inputs=_make_segwit_transaction(prev_txid_byte=0x22).inputs,
                    outputs=_make_segwit_transaction(prev_txid_byte=0x22).outputs,
                    locktime=1,
                ).to_hex(),
            ],
            "same locktime",
        ),
    ],
)
def test_combine_anyonecanpay_pledges_rejects_invalid_inputs(
    pledges: list[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        combine_anyonecanpay_pledges(pledges)


# =========================================================
# _read_exact()
# =========================================================
def test_read_exact_returns_requested_number_of_bytes() -> None:
    stream = BytesIO(b"abcdef")

    assert _read_exact(stream, 3) == b"abc"


def test_read_exact_rejects_short_stream() -> None:
    stream = BytesIO(b"ab")

    with pytest.raises(TxFormatError, match="Unexpected end of transaction"):
        _read_exact(stream, 3)


# =========================================================
# _read_uint32_le()
# =========================================================
def test_read_uint32_le_reads_little_endian_integer() -> None:
    stream = BytesIO(b"\x78\x56\x34\x12")

    assert _read_uint32_le(stream) == 0x12345678


# =========================================================
# _read_uint64_le()
# =========================================================
def test_read_uint64_le_reads_little_endian_integer() -> None:
    stream = BytesIO(b"\x08\x07\x06\x05\x04\x03\x02\x01")

    assert _read_uint64_le(stream) == 0x0102030405060708


# =========================================================
# _uint32_le()
# =========================================================
def test_uint32_le_returns_little_endian_bytes() -> None:
    assert _uint32_le(0x12345678) == b"\x78\x56\x34\x12"


@pytest.mark.parametrize("value", [-1, 0x100000000])
def test_uint32_le_rejects_out_of_range_values(value: int) -> None:
    with pytest.raises(ValueError, match="uint32 out of range"):
        _uint32_le(value)


# =========================================================
# _uint64_le()
# =========================================================
def test_uint64_le_returns_little_endian_bytes() -> None:
    assert _uint64_le(0x0102030405060708) == b"\x08\x07\x06\x05\x04\x03\x02\x01"


@pytest.mark.parametrize("value", [-1, 0x10000000000000000])
def test_uint64_le_rejects_out_of_range_values(value: int) -> None:
    with pytest.raises(ValueError, match="uint64 out of range"):
        _uint64_le(value)


# =========================================================
# _read_varint()
# =========================================================
@pytest.mark.parametrize(
    ("encoded", "expected"),
    [
        (b"\xfc", 0xFC),
        (b"\xfd\x34\x12", 0x1234),
        (b"\xfe\x78\x56\x34\x12", 0x12345678),
        (
            b"\xff\x08\x07\x06\x05\x04\x03\x02\x01",
            0x0102030405060708,
        ),
    ],
)
def test_read_varint_reads_all_supported_encodings(
    encoded: bytes, expected: int
) -> None:
    assert _read_varint(BytesIO(encoded)) == expected


# =========================================================
# _encode_varint()
# =========================================================
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0xFC, b"\xfc"),
        (0xFD, b"\xfd\xfd\x00"),
        (0x1234, b"\xfd\x34\x12"),
        (0x10000, b"\xfe\x00\x00\x01\x00"),
        (
            0x0102030405060708,
            b"\xff\x08\x07\x06\x05\x04\x03\x02\x01",
        ),
    ],
)
def test_encode_varint_returns_expected_encoding(value: int, expected: bytes) -> None:
    assert _encode_varint(value) == expected


@pytest.mark.parametrize("value", [-1, 0x10000000000000000])
def test_encode_varint_rejects_invalid_values(value: int) -> None:
    message = "varint cannot be negative" if value < 0 else "varint too large"

    with pytest.raises(ValueError, match=message):
        _encode_varint(value)

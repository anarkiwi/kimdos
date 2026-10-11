"""The kimdos command line, against the simulator."""

import io

from kimdos.cli import build_parser, cmd_sim, main


def test_sim_serves_and_stores_a_directory(tmp_path):
    (tmp_path / "hello.prg").write_bytes(b"\x00\x03abc")
    args = build_parser().parse_args(["sim", "--dir", str(tmp_path)])
    out = io.StringIO()
    cmd_sim(args, io.StringIO("L HELLO\nS COPY,0300,0302\n"), out)
    assert "$0300-$0302" in out.getvalue()
    assert (tmp_path / "copy.prg").read_bytes() == b"\x00\x03abc"


def test_sim_without_directory_stops_at_monitor():
    args = build_parser().parse_args(["--org", "4000", "sim"])
    out = io.StringIO()
    cmd_sim(args, io.StringIO("Q\n"), out)
    assert "KIMDOS" in out.getvalue()


def test_build(capsys):
    main(["build"])
    assert capsys.readouterr().out.strip().endswith("kimdos-2000.ptp")


def test_bench_table(monkeypatch, capsys):
    monkeypatch.setattr(
        "kimdos.bench.report", lambda image: ([("read", 500.4, 250.6)], [("lpc", 0, 4)])
    )
    main(["bench"])
    out = capsys.readouterr().out
    assert "| read | 500 | 251 |" in out and "| lpc | 0 | 4.00 |" in out

from src.sleeper.run import main


def test_cli_list_stats(capsys):
    assert main(["--list-stats"]) == 0
    out = capsys.readouterr().out
    assert "rush_yds" in out
    assert "receptions" in out


def test_cli_single_leg_json(capsys):
    rc = main(
        [
            "--json",
            "--player",
            "Cam Skattebo",
            "--stat",
            "rush_yds",
            "--alt",
            "40",
            "--side",
            "more",
            "--mult",
            "1.34",
            "--main",
            "52.5",
        ]
    )
    assert rc == 0
    payload = capsys.readouterr().out
    assert "Cam Skattebo" in payload
    assert "1.34" in payload


def test_cli_picks_table(capsys):
    rc = main(
        [
            "--pick",
            "rush_yds,40,more,1.34,52.5",
            "--pick",
            "pass_yds,200,more,1.26,245.5",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "slip" in out
    assert "1.34" in out


def test_cli_missing_args_errors(capsys):
    assert main(["--stat", "rush_yds"]) == 1
    err = capsys.readouterr().err
    assert "single-leg" in err

import config


def test_config_loads_and_validates():
    config.validate_config()


def test_values_per_spec():
    assert config.POSITION_SIZE == 10
    assert config.MAX_TRADES_PER_DAY == 5
    assert config.STOCK_UNIVERSE == ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"]
    assert set(config.CHARGES) == {"EQUITY_DELIVERY", "EQUITY_INTRADAY"}
    assert config.CHARGES["EQUITY_INTRADAY"]["stt"]["sell_rate"] == 0.00025


def test_round_to_tick():
    assert config.round_to_tick(100.02) == 100.0
    assert config.round_to_tick(100.03) == 100.05

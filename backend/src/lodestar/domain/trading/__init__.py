"""Trading research maths: setups, analog statistics, sizing, liquidity, backtests, paper trading.

Pure functions over daily bars. Every function that evaluates day `i` reads only
bars `0..i` (no look-ahead); execution always happens on a later bar.
"""

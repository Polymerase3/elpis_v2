import backtrader as bt

class DynamicStrat(bt.Strategy):
    """
    Run multiple user-specified indicators on a single data feed.
    Pass a list of dicts as `indicator_specs` when adding the strategy:
      cerebro.addstrategy(DynamicStrat, indicator_specs=your_list)
    Each dict must have 'name' and optional 'params'.
    """
    params = (
        ('indicator_specs', []),  # list of dicts: {'name': str, 'params': dict}
    )

    def __init__(self):
        # iterate user‐requested indicators
        for spec in self.p.indicator_specs:
            name = spec.get('name', '').lower()
            params = spec.get('params', {}) or {}

            if name in ('sma', 'movingaveragesimple', 'simplemovavg'):
                period = params.get('period', 30)
                ind = bt.indicators.SimpleMovingAverage(self.data, period=period)
                ind.plotinfo.plotname = f"SMA({period})"

            elif name == 'macd':
                me1 = params.get('period_me1', 12)
                me2 = params.get('period_me2', 26)
                sig = params.get('period_signal', 9)
                ind = bt.indicators.MACD(
                    self.data,
                    period_me1=me1,
                    period_me2=me2,
                    period_signal=sig,
                    movav=bt.indicators.ExponentialMovingAverage
                )
                ind.plotinfo.plotname = f"MACD({me1},{me2},{sig})"
                ind.plotinfo.subplot = True
                ind.plotlines.macd.plotname = 'MACD'
                ind.plotlines.signal.plotname = 'Signal'

            elif name in ('kama', 'adaptivemovingaverage', 'movingaverageadaptive'):
                period = params.get('period', 30)
                fast = params.get('fast', 2)
                slow = params.get('slow', 30)
                ind = bt.indicators.AdaptiveMovingAverage(
                    self.data,
                    period=period,
                    fast=fast,
                    slow=slow
                )
                ind.plotinfo.plotname = f"KAMA({period},{fast},{slow})"

            # ... add further `elif` blocks for other indicators ...

            else:
                raise ValueError(f"Unsupported indicator: {spec.get('name')}")

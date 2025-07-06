import backtrader as bt
import pandas as pd
from elpis.crud.data import fetch_bt_dataframe
from elpis.strategies.CrossoverMA import MovingAverageCrossStrategy


if __name__ == '__main__':
    # Load data into a Pandas DataFrame (ensure an index of datetime and columns Open, High, Low, Close, Volume)
    bt_df = fetch_bt_dataframe(
    instrument_id = 12,
    uic           = None,
    asset_type    = None,
    interval_label= '1h',
    from_date     = '2025-03-01',
    to_date       = None,
    price_side    = 'mid',
    verbose       = False,
)
    #print(bt_df.head())

    # Initialize Cerebro engine
    cerebro = bt.Cerebro()
    # Add strategy with custom parameters
    cerebro.addstrategy(
        MovingAverageCrossStrategy,
        fast_period=20,
        slow_period=50,
        ma_type='tema',
        debug=True
    )

    # Create a data feed from the DataFrame
    datafeed = bt.feeds.PandasData(dataname=bt_df)
    cerebro.adddata(datafeed)

    # Set broker parameters
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addsizer(bt.sizers.PercentSizer, percents = 50)

    # Print starting portfolio value
    print('Starting Portfolio Value:', cerebro.broker.getvalue())

    # Run over the data
    cerebro.run()

    # Print final portfolio value
    print('Final Portfolio Value:', cerebro.broker.getvalue())

    # Plot the results
    cerebro.plot()
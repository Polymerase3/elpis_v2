import psycopg2
import saxo_openapi
import saxo_openapi.endpoints.chart as chart
from datetime import datetime, timedelta
import math
from elpis.config import settings
import pandas as _pd
import backtrader as _bt


def get_data_saxo(
    access_token: str,
    account_key: str,
    Uic: int,
    asset_type: str,
    interval_code: int,
    start_time: datetime,
    horizon: int,
    mode: str = 'From',
    verbose: bool = False
) -> list:
    """
    Retrieve chart data in chunks from Saxo OpenAPI and upsert directly into PostgreSQL.

    Automatically resolves the internal instrument_id by querying market.instrument
    using the unique (uic, asset_type) pair.

    Args:
        access_token: Saxo API access token.
        account_key: Saxo API account key.
        Uic: Instrument UIC for API.
        asset_type: Saxo asset type.
        interval_code: Numeric interval code.
        start_time: Datetime to start fetching from.
        horizon: Number of minutes per data period.
        mode: 'From' or 'UpTo' (currently only 'From').
        verbose: If True, print progress per chunk.

    Returns:
        List of price-entry dicts matching market.price schema.
    """
    # 1) Resolve internal instrument_id
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM market.instrument WHERE uic = %s AND asset_type = %s;",
                (Uic, asset_type)
            )
            res = cur.fetchone()
            if not res:
                raise ValueError(f"Instrument {{UIC={Uic}, asset_type={asset_type}}} not found in DB.")
            instrument_id = res[0]
    finally:
        conn.close()

    # 2) Fetch data from Saxo in chunks
    client = saxo_openapi.API(access_token=access_token)
    all_prices = []
    now = datetime.now()
    cursor_time = start_time

    total_minutes = (now - cursor_time).total_seconds() / 60
    units = total_minutes / horizon
    num_chunks = math.ceil(units / 1200)

    for idx in range(num_chunks):
        if verbose:
            print(f"Fetching chunk {idx+1}/{num_chunks} starting {cursor_time.isoformat()}")
        params = {
            'AccountKey': account_key,
            'Uic': Uic,
            'AssetType': asset_type,
            'Horizon': horizon,
            'Mode': mode,
            'Time': cursor_time.isoformat(),
            'Count': 1200
        }
        req = chart.charts.GetChartData(params=params)
        resp = client.request(req)
        data = resp.get('Data', []) or []

        for row in data:
            entry = {
                'instrument_id': instrument_id,
                'interval_id': interval_code,
                'time_price': datetime.fromisoformat(
                    row['Time'].replace('Z', '+00:00')
                ),
                'price_open': row.get('Open'),
                'price_high': row.get('High'),
                'price_low': row.get('Low'),
                'price_close': row.get('Close'),
                'price_interest': row.get('Interest'),
                'price_open_ask': row.get('OpenAsk'),
                'price_open_bid': row.get('OpenBid'),
                'price_high_ask': row.get('HighAsk'),
                'price_high_bid': row.get('HighBid'),
                'price_low_ask': row.get('LowAsk'),
                'price_low_bid': row.get('LowBid'),
                'price_close_ask': row.get('CloseAsk'),
                'price_close_bid': row.get('CloseBid'),
                'volume': row.get('Volume')
            }
            all_prices.append(entry)

        cursor_time += timedelta(minutes=1200 * horizon)

    # 3) Upsert into PostgreSQL
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn:
            with conn.cursor() as cur:
                insert_sql = '''
                INSERT INTO market.price (
                    instrument_id, interval_id, time_price,
                    price_open, price_high, price_low, price_close, price_interest,
                    price_open_ask, price_open_bid,
                    price_high_ask, price_high_bid,
                    price_low_ask, price_low_bid,
                    price_close_ask, price_close_bid,
                    volume
                ) VALUES (
                    %(instrument_id)s, %(interval_id)s, %(time_price)s,
                    %(price_open)s, %(price_high)s, %(price_low)s, %(price_close)s, %(price_interest)s,
                    %(price_open_ask)s, %(price_open_bid)s,
                    %(price_high_ask)s, %(price_high_bid)s,
                    %(price_low_ask)s, %(price_low_bid)s,
                    %(price_close_ask)s, %(price_close_bid)s,
                    %(volume)s
                )
                ON CONFLICT (instrument_id, interval_id, time_price) DO UPDATE SET
                    price_open      = EXCLUDED.price_open,
                    price_high      = EXCLUDED.price_high,
                    price_low       = EXCLUDED.price_low,
                    price_close     = EXCLUDED.price_close,
                    price_interest  = EXCLUDED.price_interest,
                    price_open_ask  = EXCLUDED.price_open_ask,
                    price_open_bid  = EXCLUDED.price_open_bid,
                    price_high_ask  = EXCLUDED.price_high_ask,
                    price_high_bid  = EXCLUDED.price_high_bid,
                    price_low_ask   = EXCLUDED.price_low_ask,
                    price_low_bid   = EXCLUDED.price_low_bid,
                    price_close_ask = EXCLUDED.price_close_ask,
                    price_close_bid = EXCLUDED.price_close_bid,
                    volume          = EXCLUDED.volume;
                '''
                cur.executemany(insert_sql, all_prices)
    finally:
        conn.close()

    return all_prices

# -----------------------------------------------------------------------------
# Plotting helper --------------------------------------------------------------
# -----------------------------------------------------------------------------

def plot_saxo_data(
    *,
    instrument_id: int | None = None,
    uic: int | None = None,
    asset_type: str | None = None,
    interval_label: str,
    from_date: str | None = None,
    to_date: str | None = None,
    price_side: str = "mid",           # 'ask' | 'bid' | 'mid'
    indicator: list[dict] | None = None,   # e.g. [{'name':'SMA','params':{'period':30}}, {'name':'MACD','params':{}}]
    verbose: bool = False,
):
    """
    Retrieve price rows from *market.price* and plot them with Backtrader.

    Parameters
    ----------
    instrument_id / uic & asset_type / interval_label / from_date / to_date
        (same meaning as before)

    price_side : {'ask','bid','mid'}
        Which side of the book to plot. “mid” falls back to average of ask/bid.

    indicator : list[dict] | None
        Dynamic indicator specification.  Each element must be a dict with:

        * ``name``   – indicator name, **case-insensitive**  
                       Supported now: ``'SMA'`` and ``'MACD'``  
                       (more can be added trivially).

        * ``params`` – dict of kwargs forwarded to the indicator constructor.
                       Omit or pass ``{}`` for defaults.

        Example::

            indicator=[
                {'name': 'SMA',  'params': {'period': 30}},
                {'name': 'MACD', 'params': {'period_me1':12,
                                            'period_me2':26,
                                            'period_signal':9}}
            ]

    verbose : bool
        If True prints SQL and DataFrame shape.
    """
    import pandas as _pd  # local import to keep top‑level clean
    import backtrader as _bt
    
    indicator = indicator or []  # ensure iterable

    # ---------------- argument handling (mirror of show_prices) ---------------
    conn = psycopg2.connect(host=settings.db_host, port=settings.db_port,
                            dbname=settings.db_name, user=settings.db_user,
                            password=settings.db_password)
    try:
        with conn.cursor() as cur:
            if instrument_id:
                cur.execute("SELECT uic, asset_type FROM market.instrument WHERE id=%s;", (instrument_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"instrument id={instrument_id} not found")
                uic, asset_type = row
                db_id = instrument_id
            else:
                if not (uic and asset_type):
                    raise ValueError("Provide instrument_id OR (uic & asset_type)")
                cur.execute("SELECT id FROM market.instrument WHERE uic=%s AND asset_type=%s;", (uic, asset_type))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Instrument uic={uic}, asset_type={asset_type} not found")
                db_id = row[0]
    finally:
        conn.close()

    _interval_map = {'1m':1,'5m':2,'15m':3,'1h':4,'4h':5,'1d':6,'1w':7,'1mo':8}
    if interval_label not in _interval_map:
        raise ValueError(f"Invalid interval '{interval_label}'")
    interval_id = _interval_map[interval_label]

    # ---------------- build SQL with filters ----------------------------------
    filters = ["instrument_id=%s", "interval_id=%s"]
    params = [db_id, interval_id]
    if from_date:
        filters.append("time_price >= %s")
        params.append(from_date)
    if to_date:
        filters.append("time_price <= %s")
        params.append(to_date)
    where_clause = " AND ".join(filters)
    sql = f"SELECT * FROM market.price WHERE {where_clause} ORDER BY time_price ASC;"

    if verbose:
        print("SQL:", sql, " params:", params)

    conn = psycopg2.connect(host=settings.db_host, port=settings.db_port,
                            dbname=settings.db_name, user=settings.db_user,
                            password=settings.db_password)
    try:
        df = _pd.read_sql_query(sql, conn, params=params, parse_dates=['time_price'])
    finally:
        conn.close()

    if df.empty:
        raise ValueError("No price data found for the given parameters.")

    # ---------------- choose columns based on asset_type ----------------------
    _has_askbid_types = {
        'FxSpot', 'CfdOnIndex', 'CfdOnFutures', 'CfdOnStock', 'StockIndex', 'ContractFutures'
    }
    if asset_type in _has_askbid_types and price_side in {'ask', 'bid'}:
        suffix = '_ask' if price_side == 'ask' else '_bid'
        o_col = 'price_open'  + suffix
        h_col = 'price_high'  + suffix
        l_col = 'price_low'   + suffix
        c_col = 'price_close' + suffix
    else:  # default OHLC (or average for 'mid')
        o_col, h_col, l_col, c_col = 'price_open', 'price_high', 'price_low', 'price_close'
        if price_side == 'mid' and asset_type in _has_askbid_types:
            for base in ('open', 'high', 'low', 'close'):
                a = df[f'price_{base}_ask']
                b = df[f'price_{base}_bid']
                df[f'price_{base}'] = (a + b) / 2

    required = [o_col, h_col, l_col, c_col]
    if not all(col in df.columns for col in required):
        raise ValueError("Chosen price side columns are not available in the dataset.")

    # -------------- build DataFrame for Backtrader ----------------------------
    bt_df = df[['time_price', o_col, h_col, l_col, c_col]].copy()
    bt_df.columns = ['datetime', 'open', 'high', 'low', 'close']
    bt_df.set_index('datetime', inplace=True)
    bt_df.sort_index(inplace=True)

    # drop rows with incomplete OHLC to avoid Backtrader TypeError
    bt_df = bt_df.dropna(subset=['open', 'high', 'low', 'close'])
    if bt_df.empty:
        raise ValueError("After dropping missing OHLC rows, no data left to plot.")

    # ensure numeric dtype
    bt_df[['open', 'high', 'low', 'close']] = bt_df[['open', 'high', 'low', 'close']].astype(float)

    # Volume/OpenInterest (Backtrader requires them)
    bt_df['volume'] = df.get('volume').reindex(bt_df.index).fillna(0).astype(float)
    bt_df['openinterest'] = 0

    if verbose:
        print("Prepared DataFrame shape:", bt_df.shape)

    # ---------------- plot with Backtrader ------------------------------------
    cerebro = _bt.Cerebro(stdstats=False)
    datafeed = _bt.feeds.PandasData(dataname=bt_df)
    cerebro.adddata(datafeed)

    # -------- dynamic indicator strategy -------------------------------------
    class _DynamicStrat(_bt.Strategy):
        def __init__(self):
            # Wire user‐requested indicators
            for spec in indicator:  # indicator is a list of dicts
                name   = spec.get('name', '').lower()
                params = spec.get('params', {}) or {}

                if name in ('sma', 'movingaveragesimple', 'simplemovavg'):
                    # Simple Moving Average
                    period = params.get('period', 30)
                    ind = _bt.indicators.SimpleMovingAverage(
                        self.data, period=period
                    )
                    ind.plotinfo.plotname = f"SMA({period})"

                elif name == 'macd':
                    # MACD = EMA(me1) - EMA(me2), signal = EMA(macd)
                    me1    = params.get('period_me1',    12)
                    me2    = params.get('period_me2',    26)
                    sig_p  = params.get('period_signal',  9)
                    ind = _bt.indicators.MACD(
                        self.data,
                        period_me1    = me1,
                        period_me2    = me2,
                        period_signal = sig_p,
                        movav         = _bt.indicators.ExponentialMovingAverage
                    )
                    ind.plotinfo.plotname    = f"MACD({me1},{me2},{sig_p})"
                    ind.plotinfo.subplot     = True     # own subplot
                    ind.plotlines.macd.plotname   = 'MACD'
                    ind.plotlines.signal.plotname = 'Signal'

                elif name in ('kama', 'adaptivemovingaverage', 'movingaverageadaptive'):
                    # Kaufman's Adaptive Moving Average (KAMA)
                    period = params.get('period', 30)
                    fast   = params.get('fast', 2)
                    slow   = params.get('slow', 30)
                    ind = _bt.indicators.AdaptiveMovingAverage(
                        self.data,
                        period = period,
                        fast   = fast,
                        slow   = slow
                    )
                    ind.plotinfo.plotname = f"KAMA({period},{fast},{slow})"

                elif name in ('kamaenvelope', 'adaptivemovingaverageenvelope'):
                    # KAMA Envelope Bands
                    period = params.get('period', 30)
                    fast   = params.get('fast', 2)
                    slow   = params.get('slow', 30)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.AdaptiveMovingAverageEnvelope(
                        self.data,
                        period = period,
                        fast   = fast,
                        slow   = slow,
                        perc   = perc
                    )
                    ind.plotinfo.plotname = f"KAMAEnv({period},{perc}%)"

                elif name in ('kamaoscillator', 'adaptivemovingaverageoscillator', 'kamaosc', 'movingaverageadaptiveoscillator'):
                    # KAMA Oscillator
                    period = params.get('period', 30)
                    fast   = params.get('fast', 2)
                    slow   = params.get('slow', 30)
                    ind = _bt.indicators.AdaptiveMovingAverageOscillator(
                        self.data,
                        period = period,
                        fast   = fast,
                        slow   = slow
                    )
                    ind.plotinfo.plotname = f"KAMAOsc({period},{fast},{slow})"
                    ind.plotinfo.subplot  = True  # own subplot
                    
                elif name in ('ao', 'awesome', 'awesomeosc', 'awesomeoscillator'):
                    # Awesome Oscillator: SMA(median, fast) - SMA(median, slow)
                    fast = params.get('fast', 5)
                    slow = params.get('slow', 34)
                    ind = _bt.indicators.AwesomeOscillator(
                        self.data,
                        fast = fast,
                        slow = slow,
                        movav = _bt.indicators.SimpleMovingAverage
                    )
                    ind.plotinfo.plotname = f"AO({fast},{slow})"
                    ind.plotinfo.subplot  = True
                    # The main line is called 'ao'
                    
                elif name in ('bbands', 'bollingerbands'):
                    # Bollinger Bands
                    period    = params.get('period', 20)
                    devfactor = params.get('devfactor', 2.0)
                    ind = _bt.indicators.BollingerBands(
                        self.data.close,
                        period    = period,
                        devfactor = devfactor,
                        movav     = _bt.indicators.SimpleMovingAverage
                    )
                    ind.plotinfo.plotname = f"BBands({period},{devfactor})"

                    # Unbind the “same color as mid” default and set your own colors:
                    ind.plotlines.top._samecolor  = False
                    ind.plotlines.top.plotcolor   = 'blue'

                    ind.plotlines.bot._samecolor  = False
                    ind.plotlines.bot.plotcolor   = 'green'

                    # (You can also tweak the middle SMA if you like)
                    ind.plotlines.mid.ls = '--'


                elif name in ('bbpct', 'bollingerbandspct', 'bollingerbandspctb'):
                    # Bollinger Bands %B
                    period    = params.get('period', 20)
                    devfactor = params.get('devfactor', 2.0)
                    ind = _bt.indicators.BollingerBandsPct(
                        self.data.close,
                        period    = period,
                        devfactor = devfactor,
                        movav     = _bt.indicators.SimpleMovingAverage
                    )
                    ind.plotinfo.plotname = f"%B({period},{devfactor})"
                    # Lines: mid, top, bot, pctb

                    # Unbind the “same color as mid” default and set your own colors:
                    ind.plotlines.top._samecolor  = False
                    ind.plotlines.top.plotcolor   = 'blue'

                    ind.plotlines.bot._samecolor  = False
                    ind.plotlines.bot.plotcolor   = 'green'

                    # (You can also tweak the middle SMA if you like)
                    ind.plotlines.mid.ls = '--'
                    
                elif name in ('cci', 'commoditychannelindex'):
                    # Commodity Channel Index
                    period = params.get('period', 20)
                    factor = params.get('factor', 0.015)
                    ind = _bt.indicators.CommodityChannelIndex(
                        self.data,
                        period=period,
                        movav=_bt.indicators.SimpleMovingAverage,
                        factor=factor,
                    )
                    ind.plotinfo.plotname = f"CCI({period},{factor})"
                    ind.plotinfo.subplot = True
                    # plotlines configuration is already built-in;
                    # you could override if you want, e.g.:
                    # ind.plotlines.cci.plotname = 'CCI'
                
                elif name in ('dpo', 'detrendedpriceoscillator'):
                    # Detrended Price Oscillator
                    period = params.get('period', 20)
                    ind = _bt.indicators.DetrendedPriceOscillator(
                        self.data,
                        period=period,
                        movav=_bt.indicators.SimpleMovingAverage
                    )
                    ind.plotinfo.plotname = f"DPO({period})"
                    ind.plotinfo.subplot  = True
                    # rename the line if you like (default is "dpo")
                    ind.plotlines.dpo.plotname = 'DPO'

                elif name in ('dema', 'doubleexponentialmovingaverage', 'movingaveragedoubleexponential'):
                    # Double Exponential Moving Average
                    period = params.get('period', 30)
                    ind = _bt.indicators.DoubleExponentialMovingAverage(
                        self.data,
                        period=period,
                        _movav=_bt.indicators.ExponentialMovingAverage
                    )
                    ind.plotinfo.plotname = f"DEMA({period})"

                elif name in ('demaenvelope', 'doubleexponentialmovingaverageenvelope'):
                    # DEMA Envelope
                    period = params.get('period', 30)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.DoubleExponentialMovingAverageEnvelope(
                        self.data,
                        period=period,
                        _movav=_bt.indicators.ExponentialMovingAverage,
                        perc=perc
                    )
                    ind.plotinfo.plotname = f"DEMAEnv({period},{perc})"
                    # keep top/bot same color as mid by default (_samecolor=True)

                elif name in ('demo', 'demooscillator', 'doubleexponentialmovingaverageoscillator'):
                    # DEMA Oscillator
                    period = params.get('period', 30)
                    ind = _bt.indicators.DoubleExponentialMovingAverageOscillator(
                        self.data,
                        period=period,
                        _movav=_bt.indicators.ExponentialMovingAverage
                    )
                    ind.plotinfo.plotname = f"DEMAOsc({period})"
                    ind.plotinfo.subplot  = True
                    # rename lines if desired:
                    ind.plotlines.dema.plotname = 'DEMA'
                    ind.plotlines._0.plotname  = 'Osc'

                elif name in ('ema', 'exponentialmovingaverage', 'movingaverageexponential'):
                    # Exponential Moving Average
                    period = params.get('period', 30)
                    ind = _bt.indicators.ExponentialMovingAverage(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"EMA({period})"

                elif name in ('emaenvelope', 'exponentialmovingaverageenvelope'):
                    # EMA Envelope
                    period = params.get('period', 30)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.ExponentialMovingAverageEnvelope(
                        self.data,
                        period=period,
                        perc=perc
                    )
                    ind.plotinfo.plotname = f"EMAEnv({period},{perc})"
                    # top and bot default to same color as mid (_samecolor=True)

                elif name in ('emaoscillator', 'emaosc', 'exponentialmovingaverageoscillator'):
                    # EMA Oscillator
                    period = params.get('period', 30)
                    ind = _bt.indicators.ExponentialMovingAverageOscillator(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"EMAOsc({period})"
                    ind.plotinfo.subplot = True
                    # rename lines
                    ind.plotlines.ema.plotname = 'EMA'
                    ind.plotlines._0.plotname  = 'Osc'
                    
                elif name == 'fractal':
                    # Fractal indicator (bearish and bullish)
                    period    = params.get('period', 5)
                    bardist   = params.get('bardist', 0.015)
                    shift     = params.get('shift_to_potential_fractal', 2)
                    ind = _bt.studies.contrib.fractal.Fractal(
                        self.data,
                        period=period,
                        bardist=bardist,
                        shift_to_potential_fractal=shift
                    )
                    ind.plotinfo.plotname = f"Fractal({period})"
                    # Customize plotlines
                    ind.plotlines.fractal_bearish.plotmarker = '^'
                    ind.plotlines.fractal_bearish.plotmarkersize = 4.0
                    ind.plotlines.fractal_bearish.plotcolor = 'lightblue'
                    ind.plotlines.fractal_bearish.plotfill = True
                    ind.plotlines.fractal_bullish.plotmarker = 'v'
                    ind.plotlines.fractal_bullish.plotmarkersize = 4.0
                    ind.plotlines.fractal_bullish.plotcolor = 'lightblue'
                    ind.plotlines.fractal_bullish.plotfill = True
                    
                elif name == 'heikinashi':
                    # Heikin Ashi candlesticks
                    ind = _bt.indicators.HeikinAshi(self.data)
                    ind.plotinfo.plotname = "HeikinAshi"
                    # Customize plotlines if desired (default styling)
                    ind.plotlines.ha_open.plotname  = 'HA Open'
                    ind.plotlines.ha_high.plotname  = 'HA High'
                    ind.plotlines.ha_low.plotname   = 'HA Low'
                    ind.plotlines.ha_close.plotname = 'HA Close'
                    
                elif name in ('highest', 'maxn'):
                    # Highest value over a period
                    period = params.get('period', 1)
                    ind = _bt.indicators.Highest(self.data, period=period)
                    ind.plotinfo.plotname = f"HIGH({period})"
                    ind.plotinfo.subplot = True

                elif name in ('hma', 'hullmovingaverage', 'hullma'):
                    # Hull Moving Average
                    period = params.get('period', 30)
                    ind = _bt.indicators.HullMovingAverage(self.data, period=period)
                    ind.plotinfo.plotname = f"HMA({period})"

                elif name in ('hullenvelope', 'hmaenvelope'):
                    # Hull Moving Average Envelope
                    period = params.get('period', 30)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.HullMovingAverageEnvelope(
                        self.data, period=period, perc=perc
                    )
                    ind.plotinfo.plotname = f"HMAEnv({period},{perc})"
                    # Top/bot same color by default

                elif name in ('hmaosc', 'hullmaoscillator', 'hmaoscillator'):
                    # Hull Moving Average Oscillator
                    period = params.get('period', 30)
                    ind = _bt.indicators.HullMovingAverageOscillator(self.data, period=period)
                    ind.plotinfo.plotname = f"HMAOsc({period})"
                    ind.plotinfo.subplot = True

                elif name in ('hurst', 'hurste'):
                    # Hurst Exponent
                    period    = params.get('period', 40)
                    lag_start = params.get('lag_start', None)
                    lag_end   = params.get('lag_end', None)
                    ind = _bt.indicators.HurstExponent(
                        self.data,
                        period=period,
                        lag_start=lag_start,
                        lag_end=lag_end
                    )
                    ind.plotinfo.plotname = f"Hurst({period})"
                    ind.plotinfo.subplot = True

                elif name in ('ichimoku',):
                    # Ichimoku Cloud
                    tenkan = params.get('tenkan', 9)
                    kijun  = params.get('kijun', 26)
                    senkou = params.get('senkou', 52)
                    lead   = params.get('senkou_lead', 26)
                    chikou = params.get('chikou', 26)
                    ind = _bt.indicators.Ichimoku(
                        self.data,
                        tenkan=tenkan,
                        kijun=kijun,
                        senkou=senkou,
                        senkou_lead=lead,
                        chikou=chikou
                    )
                    ind.plotinfo.plotname = "Ichimoku"
                    # color the cloud bands
                    ind.plotlines.senkou_span_a.plotname = 'SpanA'
                    ind.plotlines.senkou_span_b.plotname = 'SpanB'
                    ind.plotlines.senkou_span_a._fill_gt = ( 'senkou_span_b', 'g' )  # green above
                    ind.plotlines.senkou_span_a._fill_lt = ( 'senkou_span_b', 'r' )  # red below

                elif name in ('lagf', 'laguerrefilter'):
                    # Laguerre Filter
                    period = params.get('period', 1)
                    gamma  = params.get('gamma', 0.5)
                    ind = _bt.indicators.LaguerreFilter(
                        self.data,
                        period=period,
                        gamma=gamma
                    )
                    ind.plotinfo.plotname = f"LAGF({period},{gamma})"

                elif name in ('lrsi', 'laguerrersi'):
                    # Laguerre RSI
                    period = params.get('period', 6)
                    gamma  = params.get('gamma', 0.5)
                    ind = _bt.indicators.LaguerreRSI(
                        self.data,
                        period=period,
                        gamma=gamma
                    )
                    ind.plotinfo.plotname = f"LRSI({period},{gamma})"
                    ind.plotinfo.subplot    = True
                    ind.plotinfo.plotymargin = 0.15
                    # Set tick lines for RSI scale
                    ind.plotinfo.plotyticks = [0.0, 0.2, 0.5, 0.8, 1.0]

                elif name in ('lowest', 'minn'):
                    # Lowest Value over period
                    period = params.get('period', 1)
                    ind = _bt.indicators.Lowest(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"Lowest({period})"
                    ind.plotinfo.subplot = True

                elif name in ('macdhisto', 'macdhistogram'):
                    # MACD Histogram
                    me1    = params.get('period_me1',    12)
                    me2    = params.get('period_me2',    26)
                    sig_p  = params.get('period_signal',  9)
                    ind = _bt.indicators.MACDHisto(
                        self.data,
                        period_me1    = me1,
                        period_me2    = me2,
                        period_signal = sig_p,
                        movav         = _bt.indicators.ExponentialMovingAverage
                    )
                    ind.plotinfo.plotname    = f"MACDHisto({me1},{me2},{sig_p})"
                    ind.plotinfo.subplot     = True
                    # signal line dashed
                    ind.plotlines.signal.plotinfo.plotname = 'Signal'
                    ind.plotlines.signal.plotinfo.ls       = '--'
                    # histogram bar style
                    ind.plotlines.histo.plotinfo.plotname  = 'Histo'
                    ind.plotlines.histo.plotinfo._method   = 'bar'
                    ind.plotlines.histo.plotinfo.alpha     = 0.5
                    ind.plotlines.histo.plotinfo.width     = 1.0

                elif name in ('meandev', 'meandeviation', 'meandev'):
                    # Mean Deviation
                    period = params.get('period', 20)
                    movav  = params.get('movav', _bt.indicators.SimpleMovingAverage)
                    ind = _bt.indicators.MeanDeviation(
                        self.data.close,  # deviation is typically from close price
                        period=period,
                        movav=movav
                    )
                    ind.plotinfo.plotname    = f"MeanDev({period})"
                    ind.plotinfo.subplot     = True
                    ind.plotinfo.plotlinevalues = True
                    
                elif name in ('ols_betan',):
                    # OLS BetaN: regression of close on open (for example)
                    period = params.get('period', 10)
                    ind = _bt.indicators.OLS_BetaN(
                        data0=self.data.open,    # independent variable
                        data1=self.data.close,   # dependent variable
                        period=period
                    )
                    ind.plotinfo.plotname = f"OLS_BetaN({period})"
                    ind.plotinfo.subplot  = True

                elif name in ('ols_slope_interceptn',):
                    # OLS_Slope_InterceptN: slope & intercept from OLS(close ~ open)
                    period           = params.get('period', 10)
                    prepend_constant = params.get('prepend_constant', True)
                    ind = _bt.indicators.OLS_Slope_InterceptN(
                        data0=self.data.open,
                        data1=self.data.close,
                        period=period,
                        prepend_constant=prepend_constant
                    )
                    ind.plotinfo.plotname = f"OLS_SlopeInterceptN({period})"
                    ind.plotinfo.subplot  = True
                    # rename lines
                    ind.plotlines.slope.plotname     = 'Slope'
                    ind.plotlines.intercept.plotname = 'Intercept'

                elif name in ('ols_transformationn',):
                    # OLS_TransformationN: z‐score of residuals from regression(close ~ open)
                    period = params.get('period', 10)
                    ind = _bt.indicators.OLS_TransformationN(
                        data0=self.data.open,
                        data1=self.data.close,
                        period=period
                    )
                    ind.plotinfo.plotname = f"OLS_TransformN({period})"
                    ind.plotinfo.subplot  = True
                    # expose its lines
                    ind.plotlines.spread.plotname       = 'Spread'
                    ind.plotlines.spread_mean.plotname  = 'Mean'
                    ind.plotlines.spread_std.plotname   = 'Std'
                    ind.plotlines.zscore.plotname       = 'Z-Score'

                elif name in ('pctchange', 'percentchange', 'pctchange'):
                    # PercentChange: percent change from period bars ago
                    period = params.get('period', 30)
                    ind = _bt.indicators.PctChange(
                        self.data.close,  # by default use close price
                        period=period
                    )
                    ind.plotinfo.plotname = f"%Change({period})"
                    ind.plotinfo.subplot  = True

                elif name in ('pctrank', 'percentrank', 'pctrank'):
                    # PercentRank: percentile rank over past period
                    period = params.get('period', 50)
                    func   = params.get('func', None)
                    ind = _bt.indicators.PctRank(
                        self.data.close,
                        period=period,
                        func=func
                    )
                    ind.plotinfo.plotname = f"%Rank({period})"
                    ind.plotinfo.subplot  = True

                elif name in ('ppo', 'percentagepriceoscillator'):
                    # PPO: (EMA(short)-EMA(long))/EMA(long) * 100
                    p1 = params.get('period1', 12)
                    p2 = params.get('period2', 26)
                    ps = params.get('period_signal', 9)
                    movav = params.get('movav', _bt.indicators.ExponentialMovingAverage)
                    ind = _bt.indicators.PPO(
                        self.data.close,
                        period1=p1,
                        period2=p2,
                        period_signal=ps,
                        movav=movav
                    )
                    ind.plotinfo.plotname = f"PPO({p1},{p2},{ps})"
                    ind.plotinfo.subplot  = True
                    # rename its lines
                    ind.plotlines.ppo.plotname    = 'PPO'
                    ind.plotlines.signal.plotname = 'Signal'
                    ind.plotlines.histo.plotname  = 'Hist'
                    ind.plotlines.histo._method   = 'bar'
                    ind.plotlines.histo.alpha     = 0.5
                    ind.plotlines.histo.width     = 1.0

                elif name in ('pposhort', 'pposhort', 'percentagepriceoscillatorshort'):
                    # PPOShort: (EMA(short)-EMA(long))/EMA(short) * 100
                    p1 = params.get('period1', 12)
                    p2 = params.get('period2', 26)
                    ps = params.get('period_signal', 9)
                    movav = params.get('movav', _bt.indicators.ExponentialMovingAverage)
                    ind = _bt.indicators.PPOShort(
                        self.data.close,
                        period1=p1,
                        period2=p2,
                        period_signal=ps,
                        movav=movav
                    )
                    ind.plotinfo.plotname = f"PPOShort({p1},{p2},{ps})"
                    ind.plotinfo.subplot  = True
                    ind.plotlines.ppo.plotname    = 'PPO'
                    ind.plotlines.signal.plotname = 'Signal'
                    ind.plotlines.histo.plotname  = 'Hist'
                    ind.plotlines.histo._method   = 'bar'
                    ind.plotlines.histo.alpha     = 0.5
                    ind.plotlines.histo.width     = 1.0

                elif name in ('pivot', 'pivotpoint'):
                    # PivotPoint: classic daily/monthly pivot levels
                    use_open   = params.get('open', False)
                    use_close  = params.get('close', False)
                    autoplot   = params.get('_autoplot', True)
                    # The PivotPoint indicator typically requires a higher timeframe data feed
                    # and will auto-plot on the main data if autoplot=True.
                    ind = _bt.indicators.PivotPoint(
                        self.data,        # or self.data1 if using a resampled feed at a different timeframe
                        open=use_open,
                        close=use_close,
                        _autoplot=autoplot
                    )
                    # Rename plotted lines
                    ind.plotlines.p.plotname  = 'Pivot'
                    ind.plotlines.s1.plotname = 'S1'
                    ind.plotlines.s2.plotname = 'S2'
                    ind.plotlines.r1.plotname = 'R1'
                    ind.plotlines.r2.plotname = 'R2'
                    # Keep them all on the main chart
                    ind.plotinfo.subplot = False

                elif name in ('pgo', 'prettygoodoscillator', 'prettygoodosc'):
                    # PrettyGoodOscillator: (close − SMA(close, period)) / ATR(period)
                    period = params.get('period', 14)
                    ind = _bt.indicators.PrettyGoodOscillator(
                        self.data.close,
                        period=period
                    )
                    ind.plotinfo.plotname = f"PGO({period})"
                    ind.plotinfo.subplot  = True
                    # Rename the single output line
                    ind.plotlines.pgo.plotname = 'PGO'
                    
                elif name in ('rsi_ema', 'rsi_ema', 'rsi_exponential', 'rsi'):
                    # RSI using ExponentialMovingAverage
                    period    = params.get('period',      14)
                    movav     = params.get('movav',       _bt.indicators.ExponentialMovingAverage)
                    upperband = params.get('upperband',   70.0)
                    lowerband = params.get('lowerband',   30.0)
                    safediv   = params.get('safediv',     False)
                    safehigh  = params.get('safehigh',    100.0)
                    safelow   = params.get('safelow',     50.0)
                    lookback  = params.get('lookback',    1)
                    ind = _bt.indicators.RSI(
                        self.data.close,
                        period     = period,
                        movav      = movav,
                        upperband  = upperband,
                        lowerband  = lowerband,
                        safediv    = safediv,
                        safehigh   = safehigh,
                        safelow    = safelow,
                        lookback   = lookback
                    )
                    ind.plotinfo.plotname    = f"RSI_EMA({period})"
                    ind.plotinfo.subplot     = True
                    ind.plotlines.rsi.plotname = 'RSI'

                elif name in ('rsi_sma', 'rsi_sma', 'rsi_simple', 'rsi_cutler'):
                    # RSI using SimpleMovingAverage
                    period    = params.get('period',      14)
                    movav     = params.get('movav',       _bt.indicators.SimpleMovingAverage)
                    upperband = params.get('upperband',   70.0)
                    lowerband = params.get('lowerband',   30.0)
                    safediv   = params.get('safediv',     False)
                    safehigh  = params.get('safehigh',    100.0)
                    safelow   = params.get('safelow',     50.0)
                    lookback  = params.get('lookback',    1)
                    ind = _bt.indicators.RSI(
                        self.data.close,
                        period     = period,
                        movav      = movav,
                        upperband  = upperband,
                        lowerband  = lowerband,
                        safediv    = safediv,
                        safehigh   = safehigh,
                        safelow    = safelow,
                        lookback   = lookback
                    )
                    ind.plotinfo.plotname    = f"RSI_SMA({period})"
                    ind.plotinfo.subplot     = True
                    ind.plotlines.rsi.plotname = 'RSI'

                elif name in ('roc', 'rateofchange'):
                    # Rate of Change
                    period = params.get('period', 12)
                    ind = _bt.indicators.RateOfChange(
                        self.data.close,
                        period=period
                    )
                    ind.plotinfo.plotname = f"ROC({period})"
                    ind.plotinfo.subplot  = True
                    ind.plotlines.roc.plotname = 'ROC'

                elif name in ('rmi', 'relativemomentumindex'):
                    # Relative Momentum Index
                    period = params.get('period', 20)
                    lookback = params.get('lookback', 5)
                    movav = params.get('movav', _bt.indicators.SmoothedMovingAverage)
                    ind = _bt.indicators.RelativeMomentumIndex(
                        self.data.close,
                        period=period,
                        movav=movav,
                        lookback=lookback
                    )
                    ind.plotinfo.plotname = f"RMI({period},{lookback})"
                    ind.plotinfo.subplot  = True
                    ind.plotlines.rsi.plotname = 'RMI'

                elif name in ('rsi', 'relativestrengthindex', 'rsi_smma', 'rsi_wilder'):
                    # Relative Strength Index (Wilder’s smoothing)
                    period    = params.get('period',    14)
                    movav     = params.get('movav',     _bt.indicators.SmoothedMovingAverage)
                    upperband = params.get('upperband', 70.0)
                    lowerband = params.get('lowerband', 30.0)
                    safediv   = params.get('safediv',   False)
                    safehigh  = params.get('safehigh', 100.0)
                    safelow   = params.get('safelow',   50.0)
                    lookback  = params.get('lookback',  1)
                    ind = _bt.indicators.RelativeStrengthIndex(
                        self.data.close,
                        period=period,
                        movav=movav,
                        upperband=upperband,
                        lowerband=lowerband,
                        safediv=safediv,
                        safehigh=safehigh,
                        safelow=safelow,
                        lookback=lookback
                    )
                    ind.plotinfo.plotname = f"RSI({period})"
                    ind.plotinfo.subplot  = True
                    ind.plotlines.rsi.plotname = 'RSI'

                elif name in ('smma', 'wildorma', 'movingaveragesmoothed', 'movingaveragewilder', 'modifiedmovingaverage'):
                    # Smoothed (Wilder) Moving Average
                    period = params.get('period', 30)
                    ind = _bt.indicators.SmoothingMovingAverage(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"SMMA({period})"
                    
                elif name in ('smmaenvelope', 'wildormaenvelope', 'movingaveragesmoothedenvelope',
                            'movingaveragewilderenvelope', 'modifiedmovingaverageenvelope'):
                    # Smoothed MA Envelope
                    period = params.get('period', 30)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.SmoothingMovingAverageEnvelope(
                        self.data,
                        period=period,
                        perc=perc
                    )
                    ind.plotinfo.plotname = f"SMMAEnv({period},{perc})"
                    # keep bands same color as the smma line
                    ind.plotlines.top._samecolor = True
                    ind.plotlines.bot._samecolor = True
                    
                elif name in ('smmalegoscillator', 'smmaoscillator', 'wildermaoscillator',
                            'movingaveragesmoothedoscillator', 'movingaveragewilderoscillator',
                            'modifiedmovingaverageoscillator'):
                    # Smoothed MA Oscillator
                    period = params.get('period', 30)
                    ind = _bt.indicators.SmoothedMovingAverageOscillator(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"SMMAOsc({period})"
                    ind.plotinfo.subplot = True
                    # the line is exposed as 'smma'
                    ind.plotlines.smma._name = 'SMMA'

                elif name in ('stddev', 'standarddeviation'):
                    # Standard Deviation
                    period = params.get('period', 20)
                    movav  = params.get('movav', _bt.indicators.SimpleMovingAverage)
                    safepow = params.get('safepow', False)

                    ind = _bt.indicators.StandardDeviation(
                        self.data,
                        period=period,
                        movav=movav,
                        safepow=safepow
                    )
                    ind.plotinfo.plotname = f"StdDev({period})"
                    ind.plotinfo.subplot  = True
                    
                elif name in ('stochastic', 'stochasticslow'):
                    # Slow Stochastic Oscillator
                    period      = params.get('period', 14)
                    period_dfast= params.get('period_dfast', 3)
                    movav       = params.get('movav', _bt.indicators.SimpleMovingAverage)
                    upperband   = params.get('upperband', 80.0)
                    lowerband   = params.get('lowerband', 20.0)
                    safediv     = params.get('safediv', False)
                    safezero    = params.get('safezero', 0.0)
                    period_dslow= params.get('period_dslow', 3)

                    ind = _bt.indicators.StochasticSlow(
                        self.data,
                        period=period,
                        period_dfast=period_dfast,
                        period_dslow=period_dslow,
                        movav=movav,
                        upperband=upperband,
                        lowerband=lowerband,
                        safediv=safediv,
                        safezero=safezero
                    )
                    ind.plotinfo.plotname = f"StochSlow({period},{period_dfast},{period_dslow})"
                    ind.plotinfo.subplot  = True
                    # Use dashed line for %D
                    ind.plotlines.percD.plotname = '%D'
                    ind.plotlines.percD.ls       = '--'
                    ind.plotlines.percK.plotname = '%K'

                elif name in ('stochasticfast', 'faststochastic'):
                    # Fast Stochastic Oscillator
                    period       = params.get('period', 14)
                    period_dfast = params.get('period_dfast', 3)
                    movav        = params.get('movav', _bt.indicators.SimpleMovingAverage)
                    upperband    = params.get('upperband', 80.0)
                    lowerband    = params.get('lowerband', 20.0)
                    safediv      = params.get('safediv', False)
                    safezero     = params.get('safezero', 0.0)

                    ind = _bt.indicators.StochasticFast(
                        self.data,
                        period=period,
                        period_dfast=period_dfast,
                        movav=movav,
                        upperband=upperband,
                        lowerband=lowerband,
                        safediv=safediv,
                        safezero=safezero
                    )
                    ind.plotinfo.plotname = f"StochFast({period},{period_dfast})"
                    ind.plotinfo.subplot  = True
                    # dashed %D line
                    ind.plotlines.percD.plotname = '%D'
                    ind.plotlines.percD.ls       = '--'
                    ind.plotlines.percK.plotname = '%K'

                elif name in ('stochasticfull', 'fullstochastic'):
                    # Full Stochastic Oscillator
                    period        = params.get('period', 14)
                    period_dfast  = params.get('period_dfast', 3)
                    period_dslow  = params.get('period_dslow', 3)
                    movav         = params.get('movav', _bt.indicators.SimpleMovingAverage)
                    upperband     = params.get('upperband', 80.0)
                    lowerband     = params.get('lowerband', 20.0)
                    safediv       = params.get('safediv', False)
                    safezero      = params.get('safezero', 0.0)

                    ind = _bt.indicators.StochasticFull(
                        self.data,
                        period=period,
                        period_dfast=period_dfast,
                        period_dslow=period_dslow,
                        movav=movav,
                        upperband=upperband,
                        lowerband=lowerband,
                        safediv=safediv,
                        safezero=safezero
                    )
                    ind.plotinfo.plotname = f"StochFull({period},{period_dfast},{period_dslow})"
                    ind.plotinfo.subplot  = True
                    # dashed %D line, custom labels
                    ind.plotlines.percD.plotname      = '%D'
                    ind.plotlines.percD.ls            = '--'
                    ind.plotlines.percK.plotname      = '%K'
                    ind.plotlines.percDSlow.plotname  = '%DSlow'
                    
                elif name in ('tema', 'tripleexponentialmovingaverage'):
                    # Triple Exponential Moving Average
                    period = params.get('period', 30)
                    movav  = params.get('_movav', _bt.indicators.ExponentialMovingAverage)
                    ind = _bt.indicators.TripleExponentialMovingAverage(
                        self.data,
                        period=period,
                        movav=movav
                    )
                    ind.plotinfo.plotname = f"TEMA({period})"

                elif name in ('temaenvelope', 'tripleexponentialmovingaverageenvelope'):
                    # TEMA Envelope Bands
                    period = params.get('period', 30)
                    movav  = params.get('_movav', _bt.indicators.ExponentialMovingAverage)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.TripleExponentialMovingAverageEnvelope(
                        self.data,
                        period=period,
                        movav=movav,
                        perc=perc
                    )
                    ind.plotinfo.plotname = f"TEMAEnv({period},{perc})"
                    # top & bot same color as tema
                    ind.plotlines.top._samecolor = True
                    ind.plotlines.bot._samecolor = True

                elif name in ('temao', 'temaoscillator', 'tripleexponentialmovingaverageoscillator'):
                    # TEMA Oscillator
                    period = params.get('period', 30)
                    movav  = params.get('_movav', _bt.indicators.ExponentialMovingAverage)
                    ind = _bt.indicators.TripleExponentialMovingAverageOscillator(
                        self.data,
                        period=period,
                        movav=movav
                    )
                    ind.plotinfo.plotname = f"TEMAOsc({period})"
                    ind.plotinfo.subplot  = True
                    ind.plotlines._0._name = 'osc'

                elif name in ('trix',):
                    # TRIX (Triple Exponential Moving Average Oscillator)
                    period     = params.get('period', 15)
                    rocperiod  = params.get('_rocperiod', 1)
                    movav      = params.get('_movav', _bt.indicators.ExponentialMovingAverage)
                    ind = _bt.indicators.Trix(
                        self.data,
                        period=period,
                        _rocperiod=rocperiod,
                        movav=movav
                    )
                    ind.plotinfo.plotname = f"TRIX({period},{rocperiod})"
                    ind.plotinfo.subplot  = True
                    # add zero line
                    ind.plotinfo.plothlines = [0.0]

                elif name in ('trixsignal',):
                    # TRIX with signal line
                    period     = params.get('period', 15)
                    rocperiod  = params.get('_rocperiod', 1)
                    movav      = params.get('_movav', _bt.indicators.ExponentialMovingAverage)
                    sigperiod  = params.get('sigperiod', 9)
                    ind = _bt.indicators.TrixSignal(
                        self.data,
                        period=period,
                        _rocperiod=rocperiod,
                        movav=movav,
                        period_signal=sigperiod
                    )
                    ind.plotinfo.plotname = f"TRIXSig({period},{rocperiod},{sigperiod})"
                    ind.plotinfo.subplot  = True
                    # rename lines
                    ind.plotlines.trix.plotname   = 'TRIX'
                    ind.plotlines.signal.plotname = 'Signal'
                    ind.plotinfo.plothlines       = [0.0]
                    
                elif name in ('tsi', 'truestrengthindicator', 'true_strength_index'):
                    # True Strength Index
                    period1 = params.get('period1', 25)
                    period2 = params.get('period2', 13)
                    pchange = params.get('pchange', 1)
                    movav   = params.get('_movav', _bt.indicators.ExponentialMovingAverage)
                    ind = _bt.indicators.TrueStrengthIndex(
                        self.data,
                        period1=period1,
                        period2=period2,
                        pchange=pchange,
                        movav=movav
                    )
                    ind.plotinfo.plotname = f"TSI({period1},{period2},{pchange})"
                    ind.plotinfo.subplot  = True

                elif name in ('uo', 'ultimateoscillator', 'ultimate_oscillator'):
                    # Ultimate Oscillator
                    p1         = params.get('p1', 7)
                    p2         = params.get('p2', 14)
                    p3         = params.get('p3', 28)
                    upperband  = params.get('upperband', 70.0)
                    lowerband  = params.get('lowerband', 30.0)
                    ind = _bt.indicators.UltimateOscillator(
                        self.data,
                        p1=p1,
                        p2=p2,
                        p3=p3,
                        upperband=upperband,
                        lowerband=lowerband
                    )
                    ind.plotinfo.plotname = f"UO({p1},{p2},{p3})"
                    ind.plotinfo.subplot  = True
                    # Optionally add horizontal bands
                    ind.plotinfo.plothlines = [lowerband, upperband]
                elif name in ('upday',):
                    # UpDay: max(close - close_prev, 0)
                    period = params.get('period', 1)
                    ind = _bt.indicators.UpDay(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"UpDay({period})"
                    ind.plotinfo.subplot  = True

                elif name in ('updaybool',):
                    # UpDayBool: boolean close > close_prev
                    period = params.get('period', 1)
                    ind = _bt.indicators.UpDayBool(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"UpDayBool({period})"
                    ind.plotinfo.subplot  = True

                elif name in ('upmove',):
                    # UpMove: data - data(-1)
                    ind = _bt.indicators.UpMove(
                        self.data
                    )
                    ind.plotinfo.plotname = "UpMove"
                    ind.plotinfo.subplot  = True
                elif name in ('weightedaverage', 'averageweighted'):
                    # Weighted Average over period with optional coef and weights
                    period  = params.get('period', 1)
                    coef    = params.get('coef', 1.0)
                    weights = params.get('weights', None)
                    ind = _bt.indicators.WeightedAverage(
                        self.data,
                        period=period,
                        coef=coef,
                        weights=weights
                    )
                    ind.plotinfo.plotname = f"WAvg({period},{coef})"
                    ind.plotinfo.subplot  = True

                elif name in ('wma', 'movingaverageweighted', 'weightedmovingaverage'):
                    # Weighted Moving Average
                    period = params.get('period', 30)
                    ind = _bt.indicators.WeightedMovingAverage(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"WMA({period})"

                elif name in ('wmaenvelope', 'movingaverageweightedenvelope', 'wmaenvelope'):
                    # Weighted Moving Average Envelope
                    period = params.get('period', 30)
                    perc   = params.get('perc', 2.5)
                    ind = _bt.indicators.WeightedMovingAverageEnvelope(
                        self.data,
                        period=period,
                        perc=perc
                    )
                    ind.plotinfo.plotname = f"WMAEnv({period},{perc})"

                elif name in ('wmaoscillator', 'weightedmovingaverageoscillator', 'wmaosc'):
                    # Weighted Moving Average Oscillator
                    period = params.get('period', 30)
                    ind = _bt.indicators.WeightedMovingAverageOscillator(
                        self.data,
                        period=period
                    )
                    ind.plotinfo.plotname = f"WMAOsc({period})"
                    ind.plotinfo.subplot  = True

                elif name in ('williamsad',):
                    # Williams Accumulation/Distribution
                    ind = _bt.indicators.WilliamsAD(
                        self.data
                    )
                    ind.plotinfo.plotname = "WilliamsAD"
                    ind.plotinfo.subplot  = True

                elif name in ('williamsr',):
                    # Williams %R
                    period    = params.get('period', 14)
                    upperband = params.get('upperband', -20.0)
                    lowerband = params.get('lowerband', -80.0)
                    ind = _bt.indicators.WilliamsR(
                        self.data,
                        period=period,
                        upperband=upperband,
                        lowerband=lowerband
                    )
                    ind.plotinfo.plotname = f"WR({period})"
                    ind.plotinfo.subplot  = True
                    ind.plotlines.percR.plotname = 'R%'

                else:
                    raise ValueError(f"Unsupported indicator: {spec.get('name')}")

    cerebro.addstrategy(_DynamicStrat)
    cerebro.run()

    # ----- plot; show calendar dates on x-axis -------------------------
    cerebro.plot(style='candle',
                 stdstats=False,
                 fmt_x_ticks='%Y-%m-%d\n%H:%M')

    return bt_df
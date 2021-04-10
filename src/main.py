import re
import time
import argparse
from datetime import datetime
from datetime import date
import calendar
import json
import logging
from oandapyV20 import API
from oandapyV20.exceptions import V20Error
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
from oandapyV20.contrib.requests import (
    MarketOrderRequest,
    TakeProfitDetails,
    StopLossDetails
)

from oandapyV20.definitions.instruments import CandlestickGranularity
from authentication import authentication

""" Simple trading application based on Opening Range Breakout
    strategy for intraday trading systems
    **********************************************************
    * THIS PROGRAM IS SOLELY MEANT FOR DEMONSTRATION PURPOSE!*
    * NEVER USE THIS ON A LIVE ACCOUNT                       *
    **********************************************************
    - The BotTrader class creates a PriceTable for the instrument.
    - A Opening Range Breakout indicator, ORB, is added and
      attached to the pricetable. Each time the pricetable gets a new
      record added and 'onAddItem' event is triggered which has the
      ORB calculate method attached.
    - If the current price exceeds that of high of ORB, then the
      indicator is set to LONG likewise if current price falls below
      low of ORB, then the indicator is set to SHORT,a marketorder is
      then created with a stoploss and a takeprofit where the stoploss
      is automatically set based on the STATE of indicator. Takeprofit
      can be set by the user at the time of execution
    - check the logfile to trace statechanges, orders, etc.
"""

logging.basicConfig(
    filename="./simplebot.log",
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s : %(message)s',
)

logger = logging.getLogger(__name__)


NEUTRAL = 0
SHORT = 1
LONG = 2


def mapstate(s):
    states = {
       NEUTRAL: "NEUTRAL",
       SHORT: "SHORT",
       LONG: "LONG",
    }
    return states[s]


class Event(object):

    def __init__(self):
        self.handlers = set()

    def handle(self, handler):
        logger.info("%s: adding handler: %s",
                    self.__class__.__name__, handler.__name__)
        self.handlers.add(handler)
        return self

    def unhandle(self, handler):
        try:
            self.handlers.remove(handler)
        except:
            raise ValueError("Handler is not handling this event, "
                             "so cannot unhandle it.")
        return self

    def fire(self, *args, **kargs):
        for handler in self.handlers:
            handler(*args, **kargs)

    def getHandlerCount(self):
        return len(self.handlers)

    __iadd__ = handle
    __isub__ = unhandle
    __call__ = fire
    __len__ = getHandlerCount


class Indicator(object):
    """indicater baseclass."""
    def __init__(self, pt):
        self._pt = pt
        self.values = [None] * len(self._pt._dt)

    def calculate(self):
        raise Exception("override this method")

    def __len__(self):
        return len(self._pt)

    def __getitem__(self, i):
        def rr(_i):
            if _i >= len(self._pt):  # do not go beyond idx
                raise IndexError("list assignment index out of range")
            if _i < 0:
                _i = self._pt.idx + _i

            return self.values[_i]

        if isinstance(i, int):
            return rr(i)
        elif isinstance(i, slice):
            return [rr(j) for j in range(*i.indices(len(self)))]
        else:
            raise TypeError("Invalid argument")


class ORB(Indicator):
    """Opening Range Breakout."""

    def __init__(self, pt, api,high,low):
        super(ORB, self).__init__(pt)
        self.opening_range_high, self.opening_range_low = (high, low)
        self._events = Event()
        self.state = NEUTRAL

    def calculate(self, stock_price):
        if stock_price > self.opening_range_high:
            self.state = LONG 
        elif stock_price < self.opening_range_low:
            self.state = SHORT
        logger.info("ORB: processed %s : state: %s",
                    self._pt[-1][0], mapstate(self.state))


class PriceTable(object):
    """storage of the generated events and price details"""
    def __init__(self, instrument, granularity):
        self.instrument = instrument
        self.granularity = granularity
        self._dt = [None] * 1000  # allocate space for datetime
        self._c = [None] * 1000   # allocate space for close values
        self._v = [None] * 1000   # allocate space for volume values
        self._events = {}         # registered events
        self.idx = 0

    def fireEvent(self, name, *args, **kwargs):
        if name in self._events:
            f = self._events[name]
            f(*args, **kwargs)

    def setHandler(self, name, f):
        if name not in self._events:
            self._events[name] = Event()
        self._events[name] += f

    def addItem(self, dt, c, v):
        self._dt[self.idx] = dt
        self._c[self.idx] = c
        self._v[self.idx] = v
        self.idx += 1
        self.fireEvent('onAddItem', c)

    def __len__(self):
        return self.idx

    def __getitem__(self, i):
        def rr(_i):
            if _i >= self.idx:  # do not go beyond idx in the reserved items
                raise IndexError("list assignment index out of range")
            if _i < 0:
                _i = self.idx + _i   # the actual end of the array
            return (self._dt[_i], self._c[_i], self._v[_i])

        if isinstance(i, int):
            return rr(i)
        elif isinstance(i, slice):
            return [rr(j) for j in range(*i.indices(len(self)))]
        else:
            raise TypeError("Invalid argument")


class PRecordFactory(object):
    """generate price records from streaming prices."""
    def __init__(self, granularity):
        self._last = None
        self._granularity = granularity
        self.interval = self.granularity_to_time(granularity)
        self.data = {"c": None, "v": 0}

    def parseTick(self, t):
        rec = None
        if not self._last:
            if t["type"] != "PRICE":
                return rec
            epoch = self.epochTS(t["time"])
            self._last = epoch - (epoch % self.interval)

        if self.epochTS(t["time"]) > self._last + self.interval:
            # save this record as completed
            rec = (self.secs2time(self._last), self.data['c'], self.data['v'])
            # init new one
            self._last += self.interval
            self.data["v"] = 0

        if t["type"] == "PRICE":
            self.data["c"] = (float(t['closeoutBid']) +
                              float(t['closeoutAsk'])) / 2.0
            self.data["v"] += 1

        return rec

    def granularity_to_time(self, gran):
        mfact = {'S': 1, 'M': 60, 'H': 3600, 'D': 86400}
        try:
            f, n = re.match("(?P<f>[SMHD])(?:(?P<n>\d+)|)",
                            gran).groups()
        except:
            raise ValueError("Can't handle granularity: {}".format(gran))
        else:
            n = int(n) if n else 1
            return mfact[f] * n

    def epochTS(self, t):
        d = datetime.strptime(t.split(".")[0], '%Y-%m-%dT%H:%M:%S')
        return int(calendar.timegm(d.timetuple()))

    def secs2time(self, e):
        w = time.gmtime(e)
        return datetime(*list(w)[0:6]).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


class BotTrader(object):

    def __init__(self, instrument, granularity, units, clargs):
        self.accountID, token = authentication()
        self.client = API(access_token=token)
        self.units = units
        self.clargs = clargs
        self.pt = PriceTable(instrument, granularity)
        # fetch First Candle data
        params = {
                  "count": 1,
                  "from": self.clargs.Orbdate
                  }
        r = instruments.InstrumentsCandles(instrument=instrument,
                                           params=params)
        rv = self.client.request(r)
        if len(rv) == 0:
            logger.error("No candle data available for specified date:{d}".format(d = self.clargs.Orbdate) )
            
        # and calculate indicators
        for crecord in rv['candles']:
            if crecord['complete'] is True:
                self.high = float(crecord['mid']['h'])
                self.low = float(crecord['mid']['l'])
        ORBdetails = ORB(self.pt ,self.client,self.high,self.low)
        self.pt.setHandler("onAddItem", ORBdetails.calculate)
        self.indicators = [ORBdetails]
        self.state = NEUTRAL   # overall state based on calculated indicators
        self.unit_ordered = False
        
        self._botstate()

    def _botstate(self):
        # overall state, in this case the state of the only indicator ...
        prev = self.state
        self.state = self.indicators[0].state
        units = self.units
        if self.state != prev and self.state in [SHORT, LONG]:
            logger.info("state change: from %s to %s", mapstate(prev),
                        mapstate(self.state))
            units *= (1 if self.state == LONG else -1)
            if not self.unit_ordered:
                self.order(units)

    def order(self, units):
        mop = {"instrument": self.pt.instrument,
               "units": units}

        def frmt(v):
            # format a number over 6 digits: 12004.1, 1.05455
            l = len(str(v).split(".")[0])
            return "{{:{}.{}f}}".format(l, 6-l).format(v)

        direction = 1 if units > 0 else -1
        if self.clargs.takeProfit:   # takeProfit specified? add it
            tpPrice = self.pt._c[self.pt.idx-1] * \
                      (1.0 + (self.clargs.takeProfit/100.0) * direction)
            mop.update({"takeProfitOnFill":
                        TakeProfitDetails(price=frmt(tpPrice)).data})
        #Stoploss
        if units>0:     #If position long then stoploss = low of opening range     
            slPrice = self.low
            mop.update({"stopLossOnFill":
                        StopLossDetails(price=frmt(slPrice)).data})
        elif units<0:   #If position short then stoploss = high of opening range
            slPrice = self.high
            mop.update({"stopLossOnFill":
                        StopLossDetails(price=frmt(slPrice)).data})

        data = MarketOrderRequest(**mop).data
        r = orders.OrderCreate(accountID=self.accountID, data=data)
        try:
            response = self.client.request(r)
        except V20Error as e:
            logger.error("V20Error: %s", e)
        else:
            logger.info("Response: %d %s", r.status_code,
                        json.dumps(response, indent=2))
        self.unit_ordered = True

    def run(self):
        cf = PRecordFactory(self.pt.granularity)
        r = pricing.PricingStream(accountID=self.accountID,
                                  params={"instruments": self.pt.instrument})
        for tick in self.client.request(r):
            print(tick)
            rec = cf.parseTick(tick)
            if rec:
                self.pt.addItem(*rec)

            self._botstate()


# ------------------------
if __name__ == "__main__":

    granularities = CandlestickGranularity().definitions.keys()
    # create the top-level parser
    parser = argparse.ArgumentParser(prog='simplebot')
    parser.add_argument('--takeProfit', default=0.5, type=float,
                        help='take profit value as a percentage of entryvalue')
    today = date.today()
    d1 = today.strftime("%Y-%m-%d")
    parser.add_argument('--Orbdate', default=d1+"T09:15:00Z", type=str,
                        help="YYYY-MM-DDTHH:MM:SSZ (ex. 2016-01-01T00:00:00Z)[Date and time at which ORB range will be calculated]")
    # currently appending only single instrument
    parser.add_argument('--instrument', type=str, help='instrument', required=True)
    parser.add_argument('--granularity', choices=granularities, required=True)
    parser.add_argument('--units', type=int, required=True)

    clargs = parser.parse_args()
    bot = BotTrader(instrument=clargs.instrument,
                    granularity=clargs.granularity,
                    units=clargs.units, clargs=clargs)
    bot.run()
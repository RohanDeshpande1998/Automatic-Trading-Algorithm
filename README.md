# Automatic-Trading-Algorithm
A trading bot which applies Opening Range Breakout(ORB) trading strategy using [OandaV20](https://pypi.org/project/oandapyV20) API wrapper.

## Overview
This trading bot uses API provided by [OANDA platform](https://trade.oanda.com), user initialises the bot by specifying the name of instrument, number of units and candlestick granularity, it uses ORB trading strategy to dictate its buying method(Short or Long) and calculate its stoploss. It automatically trades if the price breaches the profit-limit or stoploss.

## Features
List of features ready and TODOs for future development
* Automatically trades when price breaches ORB for an instrument
* Logfile implemented

To-do list:
* Generate concurrent stream of prices for multiple instruments

## Environment

This algorithm was built using Python 3.8.5 so it is recommended to use Python 3.x, it is recommended to create a virtual environment using a python3 command:

```
shell_prompt$: python3 -m venv <venv_name>
```

Once you have created and activated your virtual environment, synchronize your packages with the listed `requirements.txt` file in the repository.


```
(venv_name) shell_prompt$: pip install -r requirements.txt
```
## Working
1. Add your account ID in account.txt
2. Add your API code in token.txt
3. Run the main.py while specifying the trading arguments in the commandline itself. 

## Inspiration
This code is a modified version of [simplebot by hootnot](https://github.com/hootnot/oandapyV20-examples/blob/master/src/simplebot.py) 

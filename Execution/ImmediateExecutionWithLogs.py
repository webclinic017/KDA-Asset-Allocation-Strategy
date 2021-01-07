from clr import AddReference
AddReference("System")
AddReference("QuantConnect.Common")
AddReference("QuantConnect.Algorithm")
AddReference("QuantConnect.Algorithm.Framework")

from System import *
from QuantConnect import *
from QuantConnect.Orders import *
from QuantConnect.Algorithm import *
from QuantConnect.Algorithm.Framework import *
from QuantConnect.Algorithm.Framework.Execution import *
from QuantConnect.Algorithm.Framework.Portfolio import *

import numpy as np

class ImmediateExecutionWithLogsModel(ExecutionModel):
    
    '''
    Description:
        Custom implementation of IExecutionModel that immediately submits market orders to achieve the desired portfolio targets
    Details:
        This custom implementation includes logs with information about number of shares traded, prices, profit and profit percent
        for both long and short positions.
    '''

    def __init__(self):
        
        ''' Initializes a new instance of the ImmediateExecutionModel class '''
        
        self.targetsCollection = PortfolioTargetCollection()

    def Execute(self, algorithm, targets):
        
        '''
        Description:
            Immediately submits orders for the specified portfolio targets
        Args:
            algorithm: The algorithm instance
            targets: The portfolio targets to be ordered
        '''
        
        self.targetsCollection.AddRange(targets)
        
        if self.targetsCollection.Count > 0:
            for target in self.targetsCollection.OrderByMarginImpact(algorithm):
                # calculate remaining quantity to be ordered (this could be positive or negative)
                unorderedQuantity = OrderSizing.GetUnorderedQuantity(algorithm, target)
                # calculate the lot size for the security
                lotSize = algorithm.ActiveSecurities[target.Symbol].SymbolProperties.LotSize
                
                # this is the size of the order in terms of absolute number of shares
                orderSize = abs(unorderedQuantity)
                
                remainder = orderSize % lotSize
                missingForLotSize = lotSize - remainder
                # if the amount we are missing for +1 lot size is 1M part of a lot size
                # we suppose its due to floating point error and round up
                # Note: this is required to avoid a diff with C# equivalent
                if missingForLotSize < (lotSize / 1000000):
                    remainder -= lotSize

                # round down to even lot size
                orderSize -= remainder
                quantity = np.sign(unorderedQuantity) * orderSize
                
                # check if quantity is greater than 1 share (in absolute value to account for shorts)
                if quantity != 0:
                    # get the current holdings quantity, average price and cost
                    beforeHoldingsQuantity = algorithm.ActiveSecurities[target.Symbol].Holdings.Quantity
                    beforeHoldingsAvgPrice = algorithm.ActiveSecurities[target.Symbol].Holdings.AveragePrice
                    beforeHoldingsCost = algorithm.ActiveSecurities[target.Symbol].Holdings.HoldingsCost
                    
                    # place market order
                    algorithm.MarketOrder(target.Symbol, quantity)
                    
                    # get the new holdings quantity, average price and cost
                    newHoldingsQuantity = beforeHoldingsQuantity + quantity
                    newHoldingsAvgPrice = algorithm.ActiveSecurities[target.Symbol].Holdings.AveragePrice
                    newHoldingsCost = algorithm.ActiveSecurities[target.Symbol].Holdings.HoldingsCost
                    
                    # this is just for market on open orders because the avg price and cost won't update until order gets filled
                    # so to avoid getting previous values we just make them zero
                    if newHoldingsAvgPrice == beforeHoldingsAvgPrice and newHoldingsCost == beforeHoldingsCost:
                        newHoldingsAvgPrice = 0
                        newHoldingsCost = 0
                    
                    # calculate the profit percent and dollar profit when closing positions
                    lastPrice = algorithm.ActiveSecurities[target.Symbol].Price
                    if beforeHoldingsAvgPrice != 0 and lastPrice != 0:
                        # profit/loss percent for the trade
                        tradeProfitPercent = (((lastPrice / beforeHoldingsAvgPrice) - 1) * np.sign(beforeHoldingsQuantity)) * 100
                        # dollar profit/loss for the trade (when partially or entirely closing a position)
                        tradeDollarProfit = (lastPrice - beforeHoldingsAvgPrice) * (abs(quantity) * np.sign(beforeHoldingsQuantity))
                        # dollar profit/loss for the trade (when reversing a position from long/short to short/long)
                        tradeDollarProfitReverse = (lastPrice - beforeHoldingsAvgPrice) * beforeHoldingsQuantity
                    else:
                        tradeProfitPercent = 0
                        tradeDollarProfit = 0
                        tradeDollarProfitReverse = 0
                        
                    ### if we are not invested already the options are: ----------------------------------------------------------
                        # new holdings > 0 => going long
                        # new holdings < 0 => going short
                    if beforeHoldingsQuantity == 0:
                        if newHoldingsQuantity > 0:
                            algorithm.Log(str(target.Symbol.Value) + ': going long!'
                            + ' current total holdings: ' + str(round(quantity, 0))
                            + '; current average price: ' + str(round(newHoldingsAvgPrice, 4))
                            + '; current total holdings cost: ' + str(round(newHoldingsCost, 2)))
                        else:
                            algorithm.Log(str(target.Symbol.Value) + ': going short!'
                            + ' current total holdings: ' + str(round(quantity, 0))
                            + '; average price: ' + str(round(newHoldingsAvgPrice, 4))
                            + '; current total holdings cost: ' + str(round(newHoldingsCost, 2)))
                    ### -----------------------------------------------------------------------------------------------------------
                    
                    ### if we are already long the security the options are: ------------------------------------------------------
                        # new quantity > 0 => adding to long position
                        # new quantity < 0 and new holdings < before holdings => partially selling long position
                        # new quantity < 0 and new holdings = 0 => closing entire long position
                        # new quantity < 0 and new holdings < 0 => closing entire long position and going short
                    elif beforeHoldingsQuantity > 0:
                        if quantity > 0:
                            algorithm.Log(str(target.Symbol.Value) + ': adding to current long position!'
                            + ' additional shares: ' + str(round(quantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; current average price: ' + str(round(newHoldingsAvgPrice, 4))
                            + '; current total holdings cost: ' + str(round(newHoldingsCost, 2)))
                        
                        elif newHoldingsQuantity > 0 and newHoldingsQuantity < beforeHoldingsQuantity:  
                            algorithm.Log(str(target.Symbol.Value) + ': selling part of current long position!'
                            + ' selling shares: ' + str(round(-quantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; buying average price was: ' + str(round(beforeHoldingsAvgPrice, 4))
                            + '; approx. selling average price is: ' + str(round(lastPrice, 4))
                            + '; profit percent: ' + str(round(tradeProfitPercent, 4))
                            + '; dollar profit: ' + str(round(tradeDollarProfit, 2)))
                            
                        elif newHoldingsQuantity == 0:
                            algorithm.Log(str(target.Symbol.Value) + ': closing down entire current long position!'
                            + ' selling shares: ' + str(round(-quantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; buying average price was: ' + str(round(beforeHoldingsAvgPrice, 4))
                            + '; approx. selling average price is: ' + str(round(lastPrice, 4))
                            + '; profit percent: ' + str(round(tradeProfitPercent, 4))
                            + '; dollar profit: ' + str(round(tradeDollarProfit, 2)))
                            
                        elif newHoldingsQuantity < 0:
                            algorithm.Log(str(target.Symbol.Value) + ': closing down entire current long position and going short!'
                            + ' selling shares to close long: ' + str(round(beforeHoldingsQuantity, 0))
                            + '; profit percent on long position: ' + str(round(tradeProfitPercent, 4))
                            + '; dollar profit on long position: ' + str(round(tradeDollarProfitReverse, 2))
                            + '; selling shares to go short: ' + str(round(-newHoldingsQuantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; current average price: ' + str(round(newHoldingsAvgPrice, 4))
                            + '; current total holdings cost: ' + str(round(newHoldingsCost, 2)))
                    ### --------------------------------------------------------------------------------------------------------------
                    
                    ### if we are already short the security the options are: --------------------------------------------------------
                        # new quantity < 0 => adding to short position
                        # new quantity > 0 and new holdings > before holdings => partially buying back short position
                        # new quantity > 0 and new holdings = 0 => closing entire short position
                        # new quantity > 0 and new holdings > 0 => closing entire short position and going long
                    elif beforeHoldingsQuantity < 0:
                        if quantity < 0:
                            algorithm.Log(str(target.Symbol.Value) + ': adding to current short position!'
                            + ' additional shares: ' + str(round(quantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; current average price: ' + str(round(newHoldingsAvgPrice, 4))
                            + '; current total holdings cost: ' + str(round(newHoldingsCost, 2)))
                        
                        elif newHoldingsQuantity < 0 and newHoldingsQuantity > beforeHoldingsQuantity: 
                            algorithm.Log(str(target.Symbol.Value) + ': buying back part of current short position!'
                            + ' buying back shares: ' + str(round(quantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; shorting average price was: ' + str(round(beforeHoldingsAvgPrice, 4))
                            + '; approx. buying back average price is: ' + str(round(lastPrice, 4))
                            + '; profit percent: ' + str(round(tradeProfitPercent, 4))
                            + '; dollar profit: ' + str(round(tradeDollarProfit, 2)))
                            
                        elif newHoldingsQuantity == 0:
                            algorithm.Log(str(target.Symbol.Value) + ': closing down entire current short position!'
                            + ' buying back shares: ' + str(round(quantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; shorting average price was: ' + str(round(beforeHoldingsAvgPrice, 4))
                            + '; approx. buying back average price is: ' + str(round(lastPrice, 4))
                            + '; profit percent: ' + str(round(tradeProfitPercent, 4))
                            + '; dollar profit: ' + str(round(tradeDollarProfit, 2)))
                            
                        elif newHoldingsQuantity > 0:
                            algorithm.Log(str(target.Symbol.Value) + ': closing down entire current short position and going long!'
                            + ' buying back shares to close short: ' + str(round(-beforeHoldingsQuantity, 0))
                            + '; profit percent on short position: ' + str(round(tradeProfitPercent, 4))
                            + '; dollar profit on short position: ' + str(round(tradeDollarProfitReverse, 2))
                            + '; buying shares to go long: ' + str(round(newHoldingsQuantity, 0))
                            + '; current total holdings: ' + str(round(newHoldingsQuantity, 0))
                            + '; current average price: ' + str(round(newHoldingsAvgPrice, 4))
                            + '; current total holdings cost: ' + str(round(newHoldingsCost, 2)))
                    ### ---------------------------------------------------------------------------------------------------------------
                        
            self.targetsCollection.ClearFulfilled(algorithm)